"""Developability Filter — reads JSON from stdin, writes JSON to stdout.

Research-backed sequence liability checks for antibody CDR optimization.
Pure standard library — no external dependencies, runs in < 1 second.

Each check returns a list of hit dicts:
  {check, severity, sequence, position, description, citation}

severity: "fail" (hard reject) | "warn" (counts toward ptm_liabilities budget)

CDR-H3 detection uses the conserved Cys (position ~97) to Trp/Phe (position ~103)
anchor in the Kabat scheme. We detect it with a regex on the VH C-terminal region:
  C[A-Z]{3,30}(WGQ|WGK|FAY|FGQ) roughly covers >99% of human VH CDR-H3s.
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any


# ── CDR detection via abnumber ────────────────────────────────────────────────

def _get_cdr_positions(seq: str, scheme: str) -> tuple[str, dict[str, list[int]]]:
    """Return (chain_type, {cdr_name: [0-based seq indices]}) using abnumber.

    Mirrors the same function in cdr_mutator/run.py — supports both modern
    (pos.is_in_cdr() / pos.get_region()) and older (pos.cdr) abnumber APIs.
    Falls back to empty map if abnumber is unavailable.
    """
    from abnumber import Chain
    try:
        chain = Chain(seq.strip(), scheme=scheme, assign_germline=False)
    except TypeError:
        chain = Chain(seq.strip(), scheme=scheme)
    _raw_ct: str = chain.chain_type
    ct = "L" if _raw_ct in ("K", "L", "Kl") else _raw_ct
    cdr_map: dict[str, list[int]] = {}
    seq_idx = 0
    for pos, _aa in chain:
        in_cdr = False
        cdr_num = None
        if hasattr(pos, "is_in_cdr") and pos.is_in_cdr():
            in_cdr = True
            cdr_num = pos.get_region()[-1]   # "CDR1"[-1] → "1"
        elif hasattr(pos, "cdr") and pos.cdr is not None:
            in_cdr = True
            cdr_num = pos.cdr[-1]
        if in_cdr and cdr_num:
            key = f"CDR_{ct}{cdr_num}"
            cdr_map.setdefault(key, [])
            cdr_map[key].append(seq_idx)
        seq_idx += 1
    return ct, cdr_map


# ── Kyte-Doolittle hydrophobicity ─────────────────────────────────────────────
# Kyte J & Doolittle RF (1982) J Mol Biol 157:105-132.

_KD = {
    "A":  1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C":  2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I":  4.5,
    "L":  3.8, "K": -3.9, "M":  1.9, "F":  2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V":  4.2,
}


def _gravy(seq: str) -> float:
    vals = [_KD.get(aa, 0.0) for aa in seq.upper()]
    return sum(vals) / len(vals) if vals else 0.0


# ── pI estimation (Henderson-Hasselbalch approximation) ──────────────────────
# pKa values from Lehninger Biochemistry (5th ed.).

_PKA_POS = {"K": 10.5, "R": 12.5, "H": 6.0}
_PKA_NEG = {"D": 3.9,  "E": 4.1,  "C": 8.3, "Y": 10.1}
_PKA_NTERM = 8.0
_PKA_CTERM = 3.1


def _net_charge_at_ph(seq: str, ph: float) -> float:
    charge = 1.0 / (1.0 + 10 ** (ph - _PKA_NTERM))   # N-term
    charge -= 1.0 / (1.0 + 10 ** (_PKA_CTERM - ph))   # C-term
    for aa in seq.upper():
        if aa in _PKA_POS:
            charge += 1.0 / (1.0 + 10 ** (ph - _PKA_POS[aa]))
        if aa in _PKA_NEG:
            charge -= 1.0 / (1.0 + 10 ** (_PKA_NEG[aa] - ph))
    return charge


def _estimate_pi(seq: str) -> float:
    lo, hi = 0.0, 14.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _net_charge_at_ph(seq, mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 2)


def _net_charge(seq: str) -> int:
    pos = sum(1 for aa in seq.upper() if aa in ("K", "R", "H"))
    neg = sum(1 for aa in seq.upper() if aa in ("D", "E"))
    return pos - neg


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_n_glycosylation(vh: str) -> list[dict]:
    """N-[^P][ST] sequon — N-linked glycosylation site.
    Jefferis R (2009) Nat Rev Drug Discov 8:226-234.
    Schiestl M et al (2011) Nat Biotechnol 29:310-312.
    """
    hits = []
    for m in re.finditer(r"N[^P][ST]", vh):
        hits.append({
            "check": "N-glycosylation",
            "severity": "fail",
            "sequence": m.group(0),
            "position": m.start() + 1,
            "description": "N-linked glycosylation sequon (N-X-S/T, X≠P) — causes glycan microheterogeneity and may trigger immunogenicity.",
            "citation": "Jefferis R (2009) Nat Rev Drug Discov 8:226; Schiestl M et al (2011) Nat Biotechnol 29:310.",
        })
    return hits


def _check_deamidation(vh: str) -> list[dict]:
    """NG, NS, NT, NA, NH — asparagine deamidation hotspots.
    Robinson NE & Robinson AB (2001) PNAS 98:944-949.
    Sydow JF et al (2014) mAbs 6:613-623.
    Half-lives at pH 7.4, 37°C: NG < 1 day; NS ~5 days; NT ~25 days.
    """
    hits = []
    high = re.compile(r"N[GS]")      # fast: t½ < 5 days
    medium = re.compile(r"N[TAH]")   # slower: t½ 10-50 days
    for pat, sev in [(high, "fail"), (medium, "warn")]:
        for m in pat.finditer(vh):
            hits.append({
                "check": "Deamidation",
                "severity": sev,
                "sequence": m.group(0),
                "position": m.start() + 1,
                "description": f"Deamidation hotspot {m.group(0)} — converts Asn → Asp/isoAsp, causing charge heterogeneity and reduced potency.",
                "citation": "Robinson NE & Robinson AB (2001) PNAS 98:944; Sydow JF et al (2014) mAbs 6:613.",
            })
    return hits


def _check_isomerization(vh: str) -> list[dict]:
    """DG, DS, DT, DA, DD — aspartate isomerization / succinimide formation.
    Wakankar AA & Borchardt RT (2006) J Pharm Sci 95:2321-2336.
    Vlasak J & Ionescu R (2011) mAbs 3:253-263.
    """
    hits = []
    high = re.compile(r"D[GT]")      # fast: DG succinimide; DT rapid
    medium = re.compile(r"D[SAD]")   # moderate
    for pat, sev in [(high, "fail"), (medium, "warn")]:
        for m in pat.finditer(vh):
            hits.append({
                "check": "Isomerization",
                "severity": sev,
                "sequence": m.group(0),
                "position": m.start() + 1,
                "description": f"Asp isomerization hotspot {m.group(0)} — forms succinimide intermediate, alters backbone geometry and reduces binding.",
                "citation": "Wakankar AA & Borchardt RT (2006) J Pharm Sci 95:2321; Vlasak J & Ionescu R (2011) mAbs 3:253.",
            })
    return hits


def _check_oxidation(vh: str, cdr_positions: set[int]) -> list[dict]:
    """Met and Trp oxidation — relevant in CDR context.
    Stracke JO et al (2014) mAbs 6:1229-1242.  (Trp)
    Wei Z et al (2018) Anal Chem 90:5668-5675.  (Met)
    """
    hits = []
    for i, aa in enumerate(vh.upper()):
        if aa in ("W", "M") and i in cdr_positions:
            name = "Oxidation-Trp" if aa == "W" else "Oxidation-Met"
            desc = (
                f"{'Trp' if aa == 'W' else 'Met'} oxidation risk in CDR region — "
                "forms oxindole (Trp) or Met-sulfoxide, reducing binding affinity under oxidative stress."
            )
            cit = (
                "Stracke JO et al (2014) mAbs 6:1229." if aa == "W"
                else "Wei Z et al (2018) Anal Chem 90:5668."
            )
            hits.append({
                "check": name, "severity": "warn",
                "sequence": aa, "position": i + 1,
                "description": desc, "citation": cit,
            })
    return hits


def _check_dp_cleavage(vh: str) -> list[dict]:
    """DP — Asp-Pro peptide bond labile under acidic conditions.
    Bhatt NP et al (1990) J Biol Chem 265:4939.
    """
    return [
        {
            "check": "DP-cleavage",
            "severity": "warn",
            "sequence": m.group(0),
            "position": m.start() + 1,
            "description": "Asp-Pro peptide bond — prone to acid-catalysed cleavage during low-pH viral inactivation steps in manufacturing.",
            "citation": "Bhatt NP et al (1990) J Biol Chem 265:4939.",
        }
        for m in re.finditer(r"DP", vh.upper())
    ]


def _check_aromatic_overload(cdr_h3: str, cdr_h3_pos: int) -> list[dict]:
    """Aromatic fraction in CDR-H3 > 0.15.
    Chennamsetty N et al (2009) PNAS 106:11937-11942.
    Hydrophobic hot-spots correlate with aggregation propensity.
    """
    if not cdr_h3:
        return []
    frac = sum(1 for aa in cdr_h3.upper() if aa in "FWY") / len(cdr_h3)
    if frac > 0.15:
        return [{
            "check": "Aromatic-overload",
            "severity": "warn",
            "sequence": cdr_h3,
            "position": cdr_h3_pos + 1,
            "description": f"CDR-H3 aromatic fraction {frac:.0%} > 15% — hydrophobic hot-spot associated with colloidal instability and aggregation propensity.",
            "citation": "Chennamsetty N et al (2009) PNAS 106:11937.",
        }]
    return []


def _check_hydrophobic_patch(vh: str) -> list[dict]:
    """≥4 consecutive residues from FILMVWY — sticky hydrophobic patch.
    Jarasch A et al (2015) J Mol Biol 427:1256-1274.
    """
    hits = []
    for m in re.finditer(r"[FILMVWY]{4,}", vh.upper()):
        hits.append({
            "check": "Hydrophobic-patch",
            "severity": "warn",
            "sequence": m.group(0),
            "position": m.start() + 1,
            "description": f"Consecutive hydrophobic stretch {m.group(0)} — increases aggregation risk and non-specific binding (HIC retention).",
            "citation": "Jarasch A et al (2015) J Mol Biol 427:1256.",
        })
    return hits


def _check_pi(vh: str) -> list[dict]:
    """pI < 5.0 or pI > 9.5 — extreme pI affects PK and aggregation.
    Datta-Mannan A et al (2015) Drug Metab Dispos 43:1379-1387.
    Zheng L et al (2021) mAbs 13:1929169.
    """
    pi = _estimate_pi(vh)
    if pi < 5.0 or pi > 9.5:
        return [{
            "check": "Extreme-pI",
            "severity": "warn",
            "sequence": f"pI={pi:.1f}",
            "position": 0,
            "description": f"VH estimated pI {pi:.1f} is outside the 5–9.5 therapeutic window — extreme pI associated with short half-life, renal clearance, and FcRn binding impairment.",
            "citation": "Datta-Mannan A et al (2015) Drug Metab Dispos 43:1379; Zheng L et al (2021) mAbs 13:1929169.",
        }]
    return []


def _check_net_charge(vh: str) -> list[dict]:
    """Net charge < −4 or > +8 at pH 7.4.
    Datta-Mannan A et al (2015) Drug Metab Dispos 43:1379-1387.
    """
    charge = _net_charge(vh)
    if charge < -4 or charge > 8:
        return [{
            "check": "Net-charge",
            "severity": "warn",
            "sequence": f"charge={charge:+d}",
            "position": 0,
            "description": f"VH net charge {charge:+d} outside −4 to +8 range — highly charged antibodies show poor pharmacokinetics.",
            "citation": "Datta-Mannan A et al (2015) Drug Metab Dispos 43:1379.",
        }]
    return []


def _check_polyspecificity(cdr_h3: str, cdr_h3_pos: int) -> list[dict]:
    """≥3 basic residues (KRH) in CDR-H3 → polyspecificity / off-target risk.
    Jain T et al (2017) PNAS 114:944-949.
    Hotzel I et al (2012) mAbs 4:753-760.
    """
    n_basic = sum(1 for aa in cdr_h3.upper() if aa in "KRH")
    if n_basic >= 3:
        return [{
            "check": "Cationic-CDR-H3",
            "severity": "warn",
            "sequence": cdr_h3,
            "position": cdr_h3_pos + 1,
            "description": f"CDR-H3 contains {n_basic} basic residues (K/R/H) — positively charged CDR-H3 is the strongest predictor of polyspecificity and poly-reactive binding.",
            "citation": "Jain T et al (2017) PNAS 114:944; Hotzel I et al (2012) mAbs 4:753.",
        }]
    return []


def _check_cdr_h3_length(cdr_h3: str, cdr_h3_pos: int) -> list[dict]:
    """CDR-H3 > 20 aa — structural uncertainty, expression difficulty.
    Zemlin M et al (2003) J Mol Biol 334:733-749.
    Weitzner BD & Gray JJ (2017) PLOS Comput Biol 13:e1005625.
    """
    if len(cdr_h3) > 20:
        return [{
            "check": "Long-CDR-H3",
            "severity": "warn",
            "sequence": cdr_h3,
            "position": cdr_h3_pos + 1,
            "description": f"CDR-H3 length {len(cdr_h3)} aa exceeds 20 — long CDR-H3 loops are harder to model, fold, and express; associated with reduced thermostability.",
            "citation": "Zemlin M et al (2003) J Mol Biol 334:733; Weitzner BD & Gray JJ (2017) PLOS Comput Biol 13:e1005625.",
        }]
    return []


def _check_homopolymer(vh: str) -> list[dict]:
    """≥5 identical consecutive residues — expression and purification problems."""
    hits = []
    for m in re.finditer(r"(.)\1{4,}", vh.upper()):
        hits.append({
            "check": "Homopolymer",
            "severity": "fail",
            "sequence": m.group(0),
            "position": m.start() + 1,
            "description": f"Homopolymer run of {len(m.group(0))} identical residues ({m.group(1)}) — impairs expression, purification, and MS analysis.",
            "citation": "General manufacturing guideline.",
        })
    return hits


def _check_unpaired_cys(vh: str) -> list[dict]:
    """Odd number of Cys → unpaired disulfide risk.
    Allen MJ et al (2009) Biochemistry 48:3746-3754.
    """
    n = vh.upper().count("C")
    if n % 2 != 0:
        return [{
            "check": "Unpaired-Cys",
            "severity": "fail",
            "sequence": f"{n}×C",
            "position": 0,
            "description": f"Odd number of cysteines ({n}) in VH — unpaired Cys forms aberrant disulfides, causing aggregation and reduced potency.",
            "citation": "Allen MJ et al (2009) Biochemistry 48:3746.",
        }]
    return []


# ── Full sequence check ───────────────────────────────────────────────────────

def _assess_vh(vh: str, cdr_map: dict[str, list[int]]) -> list[dict]:
    cdr_h3_indices = sorted(cdr_map.get("CDR_H3", []))
    cdr_h3 = "".join(vh[i] for i in cdr_h3_indices if i < len(vh))
    cdr_h3_pos = cdr_h3_indices[0] if cdr_h3_indices else max(0, len(vh) - 20)
    all_cdr_positions: set[int] = {i for idxs in cdr_map.values() for i in idxs}

    hits: list[dict] = []
    hits.extend(_check_n_glycosylation(vh))
    hits.extend(_check_deamidation(vh))
    hits.extend(_check_isomerization(vh))
    hits.extend(_check_oxidation(vh, all_cdr_positions))
    hits.extend(_check_dp_cleavage(vh))
    hits.extend(_check_aromatic_overload(cdr_h3, cdr_h3_pos))
    hits.extend(_check_hydrophobic_patch(vh))
    hits.extend(_check_pi(vh))
    hits.extend(_check_net_charge(vh))
    hits.extend(_check_polyspecificity(cdr_h3, cdr_h3_pos))
    hits.extend(_check_cdr_h3_length(cdr_h3, cdr_h3_pos))
    hits.extend(_check_homopolymer(vh))
    hits.extend(_check_unpaired_cys(vh))
    return hits


# ── Main ──────────────────────────────────────────────────────────────────────

def _parse_variants(inp: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of variant dicts, each guaranteed to have 'vh' and 'vl'.

    Priority:
      1. sequences.variants  — standard batch token {n, variants: [{vh, vl, ...}]}
      2. sequences as a bare list — [{vh, vl, ...}]
      3. heavy_chain_variants + light_chain_variants — legacy parallel lists
      4. variant_N bundles — legacy individual handles
    Extra fields on each variant (scores, embeddings, …) are preserved as-is.
    """
    seq_input = inp.get("sequences")

    # Standard batch token
    if isinstance(seq_input, dict) and "variants" in seq_input:
        raw = seq_input["variants"]
    elif isinstance(seq_input, list):
        raw = seq_input
    else:
        raw = None

    if raw:
        out = []
        seen: set[str] = set()
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            vh = str(entry.get("vh") or "").strip().upper()
            vl = str(entry.get("vl") or "").strip().upper()
            if vh and vh not in seen:
                seen.add(vh)
                out.append({**entry, "vh": vh, "vl": vl})
        return out

    # Legacy parallel lists
    vh_list = inp.get("heavy_chain_variants") or []
    vl_list = inp.get("light_chain_variants") or []
    if isinstance(vh_list, list) and vh_list:
        out = []
        seen: set[str] = set()
        for i, vh in enumerate(vh_list):
            vh = str(vh).strip().upper()
            vl = str(vl_list[i]).strip().upper() if i < len(vl_list) else ""
            if vh and vh not in seen:
                seen.add(vh)
                out.append({"vh": vh, "vl": vl})
        return out

    # Legacy variant_N bundles
    out = []
    seen: set[str] = set()
    for i in range(1, 11):
        bundle = inp.get(f"variant_{i}") or {}
        if isinstance(bundle, dict):
            vh = str(bundle.get("heavy_chain") or "").strip().upper()
            vl = str(bundle.get("light_chain") or "").strip().upper()
            if vh and vh not in seen:
                seen.add(vh)
                out.append({"vh": vh, "vl": vl})
    if out:
        return out

    # Single VH/VL pair — what loop_start, sequence_input and sequence_db emit.
    # Assess it as a one-element batch so the filter works when wired directly to
    # a sequence source (not only to a variant-generating design node). Cover every
    # way a single pair can arrive: dedicated heavy_chain/light_chain inputs, or a
    # `sequences` port carrying a bare VH string or a single {heavy_chain/vh} dict.
    single_vh = str(inp.get("heavy_chain") or inp.get("vh") or "").strip().upper()
    single_vl = str(inp.get("light_chain") or inp.get("vl") or "").strip().upper()
    if not single_vh and isinstance(seq_input, str):
        single_vh = seq_input.strip().upper()
    if not single_vh and isinstance(seq_input, dict):
        single_vh = str(seq_input.get("heavy_chain") or seq_input.get("vh") or "").strip().upper()
        single_vl = single_vl or str(seq_input.get("light_chain") or seq_input.get("vl") or "").strip().upper()
    if single_vh:
        return [{"vh": single_vh, "vl": single_vl}]

    return out


def main() -> None:
    inp: dict[str, Any] = json.load(sys.stdin)

    scheme: str = str(inp.get("scheme", "imgt")).strip().lower()
    max_ptm = int(inp.get("max_ptm_liabilities", 3))
    # acquisition_scores map is a fallback; per-variant scores in the batch take priority
    acq_scores_map: dict[str, float] = inp.get("acquisition_scores") or {}

    _DEFAULT_CONFIG: dict[str, str] = {
        "N-glycosylation": "hard", "Deamidation": "warn", "Isomerization": "warn",
        "Oxidation-Trp": "warn", "Oxidation-Met": "warn", "DP-cleavage": "warn",
        "Aromatic-overload": "warn", "Hydrophobic-patch": "warn", "pI-extreme": "warn",
        "Net-charge-extreme": "warn", "Polyspecificity": "warn", "CDR-H3-length": "warn",
        "Homopolymer": "hard", "Unpaired-Cys": "hard",
    }
    check_config: dict[str, str] = dict(_DEFAULT_CONFIG)
    if inp.get("check_config"):
        check_config.update(inp["check_config"])
    elif inp.get("hard_fail_checks"):
        for k in check_config:
            check_config[k] = "hard" if k in inp["hard_fail_checks"] else check_config[k]

    hard_fails  = {k for k, v in check_config.items() if v == "hard"}
    off_checks  = {k for k, v in check_config.items() if v == "off"}
    _PTM_CHECKS = {k for k, v in check_config.items() if v == "warn"}

    variants = _parse_variants(inp)
    if not variants:
        print(json.dumps({"error": "No variants provided — wire a sequences output here."}))
        sys.exit(1)

    print(f"Assessing {len(variants)} variants…", file=sys.stderr)

    liability_report: dict[str, Any] = {}
    feasible_variants: list[dict[str, Any]] = []

    for variant in variants:
        vh = variant["vh"]
        vl = variant.get("vl", "")
        acq = float(variant.get("acquisition_score", acq_scores_map.get(vh, -999.0)))

        try:
            _, cdr_map = _get_cdr_positions(vh, scheme)
        except Exception as e:
            print(f"  CDR detection failed for {vh[:20]}… ({e}) — CDR-dependent checks skipped", file=sys.stderr)
            cdr_map = {}
        liabilities = [h for h in _assess_vh(vh, cdr_map) if h["check"] not in off_checks]

        hard_hit = any(h["check"] in hard_fails for h in liabilities)
        ptm_count = sum(1 for h in liabilities if h["check"] in _PTM_CHECKS)
        passed = not hard_hit and ptm_count <= max_ptm

        liability_report[vh] = {
            "passed": passed,
            "n_liabilities": len(liabilities),
            "n_ptm": ptm_count,
            "hard_fail": hard_hit,
            "acquisition_score": acq,
            "liabilities": liabilities,
        }

        if passed:
            # Preserve all extra fields from the incoming variant, annotate with filter results
            feasible_variants.append({
                **variant,
                "acquisition_score": acq,
                "n_liabilities": len(liabilities),
            })

        status = "PASS" if passed else "FAIL"
        fail_reason = ""
        if hard_hit:
            fail_reason = " (hard-fail: " + ", ".join(h["check"] for h in liabilities if h["check"] in hard_fails) + ")"
        elif not passed:
            fail_reason = f" (PTM count {ptm_count} > {max_ptm})"
        print(f"  {vh[:25]}… {status}{fail_reason} | {len(liabilities)} liabilities | acq={acq:.3f}", file=sys.stderr)

    # Fallback: if all variants fail, keep the best-scoring one
    if not feasible_variants and variants:
        best = max(variants, key=lambda v: float(v.get("acquisition_score", acq_scores_map.get(v["vh"], -999.0))))
        best_vh = best["vh"]
        feasible_variants.append({
            **best,
            "acquisition_score": float(best.get("acquisition_score", acq_scores_map.get(best_vh, -999.0))),
            "n_liabilities": len(liability_report.get(best_vh, {}).get("liabilities", [])),
        })
        print(f"  All variants failed — falling back to best-scoring: {best_vh[:25]}…", file=sys.stderr)

    print(f"Done: {len(feasible_variants)}/{len(variants)} variants feasible.", file=sys.stderr)

    # Output sequences in the same batch format as input
    sequences_out = {"n": len(feasible_variants), "variants": feasible_variants}

    # Legacy feasible_variants dict keyed by vh (for backward-compat wiring)
    feasible_dict = {v["vh"]: {"heavy_chain": v["vh"], "light_chain": v.get("vl", ""),
                                "acquisition_score": v.get("acquisition_score", -999.0),
                                "n_liabilities": v.get("n_liabilities", 0)}
                     for v in feasible_variants}

    result = {
        "feasible_variants": feasible_dict,
        "n_feasible": len(feasible_variants),
        "liability_report": liability_report,
    }

    print(json.dumps({
        "sequences": sequences_out,
        **result,
        "result": result,
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(traceback.format_exc(), file=sys.stderr)
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
