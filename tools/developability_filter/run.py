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


# ── CDR-H3 extraction ─────────────────────────────────────────────────────────

_CDR_H3_RE = re.compile(
    r"C([A-Z]{3,30?})(W(?:GQ|GK|GRG?|GS)|F(?:AY|GQ|DY|GY))",
    re.IGNORECASE,
)


def _find_cdr_h3(vh: str) -> str:
    """Return CDR-H3 sequence (between conserved Cys and Trp/Phe anchor)."""
    m = _CDR_H3_RE.search(vh[-60:])  # CDR-H3 is always in the last 60 residues
    if m:
        return m.group(1)
    # Fallback: last 15 residues before the final WGxG/FAY
    m2 = re.search(r"([A-Z]{5,25})(WGQG|WGKG|WGRG|FAYG)", vh, re.IGNORECASE)
    return m2.group(1) if m2 else vh[-20:-7]  # rough fallback


def _cdr_h3_start(vh: str) -> int:
    """0-based start index of CDR-H3 in vh string."""
    offset = max(0, len(vh) - 60)
    m = _CDR_H3_RE.search(vh[offset:])
    if m:
        return offset + m.start(1)
    m2 = re.search(r"([A-Z]{5,25})(WGQG|WGKG|WGRG|FAYG)", vh, re.IGNORECASE)
    return m2.start(1) if m2 else max(0, len(vh) - 20)


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


def _check_oxidation(vh: str) -> list[dict]:
    """Met and Trp oxidation — relevant in CDR context.
    Stracke JO et al (2014) mAbs 6:1229-1242.  (Trp)
    Wei Z et al (2018) Anal Chem 90:5668-5675.  (Met)
    """
    hits = []
    cdr_h3_start = _cdr_h3_start(vh)
    for i, aa in enumerate(vh.upper()):
        if aa in ("W", "M"):
            in_cdr = i >= cdr_h3_start or (30 <= i <= 36) or (50 <= i <= 66)
            sev = "warn" if in_cdr else None
            if sev:
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
                    "check": name, "severity": sev,
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


def _check_aromatic_overload(vh: str, cdr_h3: str) -> list[dict]:
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
            "position": _cdr_h3_start(vh) + 1,
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

def _assess_vh(vh: str) -> list[dict]:
    cdr_h3 = _find_cdr_h3(vh)
    cdr_h3_pos = _cdr_h3_start(vh)

    hits: list[dict] = []
    hits.extend(_check_n_glycosylation(vh))
    hits.extend(_check_deamidation(vh))
    hits.extend(_check_isomerization(vh))
    hits.extend(_check_oxidation(vh))
    hits.extend(_check_dp_cleavage(vh))
    hits.extend(_check_aromatic_overload(vh, cdr_h3))
    hits.extend(_check_hydrophobic_patch(vh))
    hits.extend(_check_pi(vh))
    hits.extend(_check_net_charge(vh))
    hits.extend(_check_polyspecificity(cdr_h3, cdr_h3_pos))
    hits.extend(_check_cdr_h3_length(cdr_h3, cdr_h3_pos))
    hits.extend(_check_homopolymer(vh))
    hits.extend(_check_unpaired_cys(vh))
    return hits


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    inp: dict[str, Any] = json.load(sys.stdin)

    max_ptm     = int(inp.get("max_ptm_liabilities", 3))
    hard_fails  = set(inp.get("hard_fail_checks") or ["N-glycosylation", "Unpaired-Cys", "Homopolymer"])
    acq_scores: dict[str, float] = inp.get("acquisition_scores") or {}

    _PTM_CHECKS = {"N-glycosylation", "Deamidation", "Isomerization", "Oxidation-Trp", "Oxidation-Met", "DP-cleavage"}

    # Collect variants
    variants: list[tuple[str, str]] = []   # (vh, vl)
    for i in range(1, 9):
        bundle = inp.get(f"variant_{i}") or {}
        if isinstance(bundle, dict):
            vh = str(bundle.get("heavy_chain") or "").strip().upper()
            vl = str(bundle.get("light_chain") or "").strip().upper()
            if vh and vh not in [v[0] for v in variants]:
                variants.append((vh, vl))

    if not variants:
        print(json.dumps({"error": "No variant inputs provided (variant_1..variant_8)"}))
        sys.exit(1)

    print(f"Assessing {len(variants)} variants…", file=sys.stderr)

    liability_report: dict[str, Any] = {}
    feasible: dict[str, Any] = {}

    for vh, vl in variants:
        liabilities = _assess_vh(vh)

        # Determine pass/fail
        hard_hit = any(h["check"] in hard_fails for h in liabilities)
        ptm_count = sum(1 for h in liabilities if h["check"] in _PTM_CHECKS)
        passed = not hard_hit and ptm_count <= max_ptm

        acq = acq_scores.get(vh, -999.0)
        liability_report[vh] = {
            "passed": passed,
            "n_liabilities": len(liabilities),
            "n_ptm": ptm_count,
            "hard_fail": hard_hit,
            "acquisition_score": acq,
            "liabilities": liabilities,
        }

        if passed:
            feasible[vh] = {
                "heavy_chain": vh,
                "light_chain": vl,
                "acquisition_score": acq,
                "n_liabilities": len(liabilities),
            }

        status = "PASS" if passed else "FAIL"
        fail_reason = ""
        if hard_hit:
            fail_reason = " (hard-fail: " + ", ".join(h["check"] for h in liabilities if h["check"] in hard_fails) + ")"
        elif not passed:
            fail_reason = f" (PTM count {ptm_count} > {max_ptm})"
        print(f"  {vh[:25]}… {status}{fail_reason} | {len(liabilities)} liabilities | acq={acq:.3f}", file=sys.stderr)

    # Fallback: if all variants fail, keep the best-scoring one
    if not feasible and variants:
        best_vh, best_vl = max(variants, key=lambda t: acq_scores.get(t[0], -999.0))
        feasible[best_vh] = {
            "heavy_chain": best_vh,
            "light_chain": best_vl,
            "acquisition_score": acq_scores.get(best_vh, -999.0),
            "n_liabilities": len(liability_report.get(best_vh, {}).get("liabilities", [])),
        }
        print(f"  All variants failed — falling back to best-scoring: {best_vh[:25]}…", file=sys.stderr)

    print(f"Done: {len(feasible)}/{len(variants)} variants feasible.", file=sys.stderr)

    result = {
        "feasible_variants": feasible,
        "n_feasible": len(feasible),
        "liability_report": liability_report,
    }

    print(json.dumps({
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
