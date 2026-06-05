#!/usr/bin/env python
"""CDR Mutator — generates antibody CDR variant libraries.

Reads JSON from stdin, writes JSON to stdout.
Runs in the biophi conda env (abnumber + sapiens + numpy already installed).

Mutation strategies
-------------------
random      : uniform random AA substitution at selected CDR positions
blosum62    : substitutions weighted by BLOSUM62 scores (conservative-biased)
conservative: substitutes only within biochemically similar property groups
sapiens     : per-position probabilities from the Sapiens BioPhi language model
saturation  : all 19 single-point substitutions at every selected CDR position
"""
import json
import math
import random
import sys
from typing import Optional


# ── BLOSUM62 substitution matrix (Henikoff & Henikoff 1992) ──────────────────
# Rows = original AA, columns = target AA, values = log-odds score.
# Only the 20 standard amino acids are included.
_AA_ORDER = "ARNDCQEGHILKMFPSTWYVBZX"  # order used in the canonical matrix
AMINO_ACIDS = list("ARNDCQEGHILKMFPSTWYV")

BLOSUM62: dict[str, dict[str, int]] = {
    "A": {"A": 4,"R":-1,"N":-2,"D":-2,"C": 0,"Q":-1,"E":-1,"G": 0,"H":-2,"I":-1,"L":-1,"K":-1,"M":-1,"F":-2,"P":-1,"S": 1,"T": 0,"W":-3,"Y":-2,"V": 0},
    "R": {"A":-1,"R": 5,"N": 0,"D":-2,"C":-3,"Q": 1,"E": 0,"G":-2,"H": 0,"I":-3,"L":-2,"K": 2,"M":-1,"F":-3,"P":-2,"S":-1,"T":-1,"W":-3,"Y":-2,"V":-3},
    "N": {"A":-2,"R": 0,"N": 6,"D": 1,"C":-3,"Q": 0,"E": 0,"G": 0,"H": 1,"I":-3,"L":-3,"K": 0,"M":-2,"F":-3,"P":-2,"S": 1,"T": 0,"W":-4,"Y":-2,"V":-3},
    "D": {"A":-2,"R":-2,"N": 1,"D": 6,"C":-3,"Q": 0,"E": 2,"G":-1,"H":-1,"I":-3,"L":-4,"K":-1,"M":-3,"F":-3,"P":-1,"S": 0,"T":-1,"W":-4,"Y":-3,"V":-3},
    "C": {"A": 0,"R":-3,"N":-3,"D":-3,"C": 9,"Q":-3,"E":-4,"G":-3,"H":-3,"I":-1,"L":-1,"K":-3,"M":-1,"F":-2,"P":-3,"S":-1,"T":-1,"W":-2,"Y":-2,"V":-1},
    "Q": {"A":-1,"R": 1,"N": 0,"D": 0,"C":-3,"Q": 5,"E": 2,"G":-2,"H": 0,"I":-3,"L":-2,"K": 1,"M": 0,"F":-3,"P":-1,"S": 0,"T":-1,"W":-2,"Y":-1,"V":-2},
    "E": {"A":-1,"R": 0,"N": 0,"D": 2,"C":-4,"Q": 2,"E": 5,"G":-2,"H": 0,"I":-3,"L":-3,"K": 1,"M":-2,"F":-3,"P":-1,"S": 0,"T":-1,"W":-3,"Y":-2,"V":-2},
    "G": {"A": 0,"R":-2,"N": 0,"D":-1,"C":-3,"Q":-2,"E":-2,"G": 6,"H":-2,"I":-4,"L":-4,"K":-2,"M":-3,"F":-3,"P":-2,"S": 0,"T":-2,"W":-2,"Y":-3,"V":-3},
    "H": {"A":-2,"R": 0,"N": 1,"D":-1,"C":-3,"Q": 0,"E": 0,"G":-2,"H": 8,"I":-3,"L":-3,"K":-1,"M":-2,"F":-1,"P":-2,"S":-1,"T":-2,"W":-2,"Y": 2,"V":-3},
    "I": {"A":-1,"R":-3,"N":-3,"D":-3,"C":-1,"Q":-3,"E":-3,"G":-4,"H":-3,"I": 4,"L": 2,"K":-3,"M": 1,"F": 0,"P":-3,"S":-2,"T":-1,"W":-3,"Y":-1,"V": 3},
    "L": {"A":-1,"R":-2,"N":-3,"D":-4,"C":-1,"Q":-2,"E":-3,"G":-4,"H":-3,"I": 2,"L": 4,"K":-2,"M": 2,"F": 0,"P":-3,"S":-2,"T":-1,"W":-2,"Y":-1,"V": 1},
    "K": {"A":-1,"R": 2,"N": 0,"D":-1,"C":-3,"Q": 1,"E": 1,"G":-2,"H":-1,"I":-3,"L":-2,"K": 5,"M":-1,"F":-3,"P":-1,"S": 0,"T":-1,"W":-3,"Y":-2,"V":-2},
    "M": {"A":-1,"R":-1,"N":-2,"D":-3,"C":-1,"Q": 0,"E":-2,"G":-3,"H":-2,"I": 1,"L": 2,"K":-1,"M": 5,"F": 0,"P":-2,"S":-1,"T":-1,"W":-1,"Y":-1,"V": 1},
    "F": {"A":-2,"R":-3,"N":-3,"D":-3,"C":-2,"Q":-3,"E":-3,"G":-3,"H":-1,"I": 0,"L": 0,"K":-3,"M": 0,"F": 6,"P":-4,"S":-2,"T":-2,"W": 1,"Y": 3,"V":-1},
    "P": {"A":-1,"R":-2,"N":-2,"D":-1,"C":-3,"Q":-1,"E":-1,"G":-2,"H":-2,"I":-3,"L":-3,"K":-1,"M":-2,"F":-4,"P": 7,"S":-1,"T":-1,"W":-4,"Y":-3,"V":-2},
    "S": {"A": 1,"R":-1,"N": 1,"D": 0,"C":-1,"Q": 0,"E": 0,"G": 0,"H":-1,"I":-2,"L":-2,"K": 0,"M":-1,"F":-2,"P":-1,"S": 4,"T": 1,"W":-3,"Y":-2,"V":-2},
    "T": {"A": 0,"R":-1,"N": 0,"D":-1,"C":-1,"Q":-1,"E":-1,"G":-2,"H":-2,"I":-1,"L":-1,"K":-1,"M":-1,"F":-2,"P":-1,"S": 1,"T": 5,"W":-2,"Y":-2,"V": 0},
    "W": {"A":-3,"R":-3,"N":-4,"D":-4,"C":-2,"Q":-2,"E":-3,"G":-2,"H":-2,"I":-3,"L":-2,"K":-3,"M":-1,"F": 1,"P":-4,"S":-3,"T":-2,"W":11,"Y": 2,"V":-3},
    "Y": {"A":-2,"R":-2,"N":-2,"D":-3,"C":-2,"Q":-1,"E":-2,"G":-3,"H": 2,"I":-1,"L":-1,"K":-2,"M":-1,"F": 3,"P":-3,"S":-2,"T":-2,"W": 2,"Y": 7,"V":-1},
    "V": {"A": 0,"R":-3,"N":-3,"D":-3,"C":-1,"Q":-2,"E":-2,"G":-3,"H":-3,"I": 3,"L": 1,"K":-2,"M": 1,"F":-1,"P":-2,"S":-2,"T": 0,"W":-3,"Y":-1,"V": 4},
}

# Biochemically similar groups for conservative mutagenesis
_CONSERVATIVE_GROUPS: list[frozenset[str]] = [
    frozenset("AG"),          # tiny, non-polar
    frozenset("ST"),          # small hydroxyl
    frozenset("NQ"),          # small amide
    frozenset("DE"),          # acidic
    frozenset("KRH"),         # basic
    frozenset("ILMV"),        # aliphatic hydrophobic
    frozenset("FWY"),         # aromatic
    frozenset("C"),           # cysteine (unique)
    frozenset("P"),           # proline (unique)
]


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ── Mutation samplers ─────────────────────────────────────────────────────────

def _random_mutant(aa: str, rng: random.Random) -> str:
    opts = [a for a in AMINO_ACIDS if a != aa]
    return rng.choice(opts)


def _blosum62_mutant(aa: str, rng: random.Random) -> str:
    row = BLOSUM62.get(aa.upper(), {})
    candidates = [a for a in AMINO_ACIDS if a != aa]
    weights = [math.exp(row.get(a, -4)) for a in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def _conservative_mutant(aa: str, rng: random.Random) -> str:
    for group in _CONSERVATIVE_GROUPS:
        if aa in group:
            opts = [a for a in group if a != aa]
            if opts:
                return rng.choice(opts)
            break
    # Fallback to BLOSUM62 if no conservative partner (e.g. lone C or P)
    return _blosum62_mutant(aa, rng)


# ── CDR detection ─────────────────────────────────────────────────────────────

def _get_cdr_positions(seq: str, scheme: str) -> tuple[str, dict[str, list[int]]]:
    """Return (chain_type, {cdr_name: [0-based seq indices]}) using abnumber.

    Supports both the modern abnumber API (pos.is_in_cdr() / pos.get_region())
    and older versions that expose pos.cdr as an attribute.
    """
    from abnumber import Chain

    try:
        chain = Chain(seq.strip(), scheme=scheme, assign_germline=False)
    except TypeError:
        chain = Chain(seq.strip(), scheme=scheme)

    # Normalize chain type: kappa='K' and lambda='L' both map to 'L' for CDR naming.
    _raw_ct: str = chain.chain_type
    ct = "L" if _raw_ct in ("K", "L", "Kl") else _raw_ct  # H stays H
    cdr_map: dict[str, list[int]] = {}
    seq_idx = 0

    for pos, _aa in chain:
        in_cdr = False
        cdr_num = None

        # Modern abnumber: pos.is_in_cdr() + pos.get_region() → "CDR1"/"CDR2"/"CDR3"
        if hasattr(pos, "is_in_cdr") and pos.is_in_cdr():
            in_cdr = True
            region = pos.get_region()          # e.g. "CDR1", "CDR2", "CDR3"
            cdr_num = region[-1]               # "1", "2", "3"
        # Older abnumber: pos.cdr attribute
        elif hasattr(pos, "cdr") and pos.cdr is not None:
            in_cdr = True
            cdr_num = pos.cdr[-1]              # "CDR1"[-1] → "1"

        if in_cdr and cdr_num:
            key = f"CDR_{ct}{cdr_num}"
            cdr_map.setdefault(key, [])
            cdr_map[key].append(seq_idx)

        seq_idx += 1

    return ct, cdr_map


# ── Sapiens per-position scores ───────────────────────────────────────────────

def _sapiens_scores(seq: str, chain_type: str) -> Optional[dict[int, dict[str, float]]]:
    """
    Call Sapiens to get per-residue AA probability distributions.
    Returns {seq_idx: {aa: prob}} or None if Sapiens is unavailable.
    """
    try:
        import sapiens  # type: ignore
        import numpy as np

        # sapiens.predict_scores accepts a raw string or an abnumber Chain.
        # We try the raw string approach first (works in most sapiens versions).
        result = sapiens.predict_scores(seq, chain_type=chain_type)

        # result may be a DataFrame, numpy array, or dict — handle all forms
        if hasattr(result, "iloc"):  # pandas DataFrame
            df = result
            scores: dict[int, dict[str, float]] = {}
            n_rows = len(df)
            cols = list(df.columns)
            for i in range(n_rows):
                row_vals = df.iloc[i].values.astype(float)
                # softmax
                row_vals -= row_vals.max()
                exp_vals = np.exp(row_vals)
                probs = exp_vals / exp_vals.sum()
                scores[i] = {c: float(p) for c, p in zip(cols, probs)
                             if c in AMINO_ACIDS}
            return scores

        if isinstance(result, np.ndarray):  # (seq_len, 20) numpy array
            if result.ndim != 2 or result.shape[1] != 20:
                return None
            scores = {}
            for i, row in enumerate(result):
                row = row.astype(float)
                row -= row.max()
                exp_vals = np.exp(row)
                probs = exp_vals / exp_vals.sum()
                scores[i] = {aa: float(p) for aa, p in zip(AMINO_ACIDS, probs)}
            return scores

    except Exception as exc:
        _progress(f"⚠ Sapiens unavailable ({exc}); falling back to BLOSUM62")
    return None


# ── Apply one mutation at a single CDR position ───────────────────────────────

def _pick_mutant(
    aa: str,
    strategy: str,
    rng: random.Random,
    sapiens_pos: Optional[dict[str, float]],
) -> str:
    if strategy == "random":
        return _random_mutant(aa, rng)

    if strategy == "blosum62":
        return _blosum62_mutant(aa, rng)

    if strategy == "conservative":
        return _conservative_mutant(aa, rng)

    if strategy == "sapiens":
        if sapiens_pos:
            candidates = [a for a, p in sapiens_pos.items()
                          if a != aa and a in AMINO_ACIDS]
            weights = [sapiens_pos[a] for a in candidates]
            total = sum(weights)
            if candidates and total > 0:
                return rng.choices(candidates, weights=weights, k=1)[0]
        # Graceful fallback
        return _blosum62_mutant(aa, rng)

    # Unknown strategy → random
    return _random_mutant(aa, rng)


# ── Generate one variant ──────────────────────────────────────────────────────

def _make_variant(
    seq: str,
    positions: list[int],
    active_cdrs: dict[str, list[int]],
    strategy: str,
    num_mutations: int,
    rng: random.Random,
    sapiens_pos_scores: Optional[dict[int, dict[str, float]]],
) -> tuple[str, list[dict]]:
    """Return (mutant_seq, [mutation_records])."""
    chosen = rng.sample(positions, min(num_mutations, len(positions)))
    seq_list = list(seq)
    records: list[dict] = []

    for pos in sorted(chosen):
        orig = seq_list[pos]
        sap = sapiens_pos_scores.get(pos) if sapiens_pos_scores else None
        new_aa = _pick_mutant(orig, strategy, rng, sap)
        seq_list[pos] = new_aa
        cdr_name = next(
            (k for k, v in active_cdrs.items() if pos in v), "unknown"
        )
        records.append({
            "position": pos + 1,   # 1-based
            "original": orig,
            "mutant": new_aa,
            "cdr": cdr_name,
        })

    return "".join(seq_list), records


# ── Saturation scan ───────────────────────────────────────────────────────────

def _saturation_variants(
    seq: str, active_cdrs: dict[str, list[int]]
) -> tuple[list[str], list[list[dict]]]:
    variants, reports = [], []
    # Sort positions for deterministic output order
    all_positions = sorted({pos for v in active_cdrs.values() for pos in v})
    for pos in all_positions:
        orig = seq[pos]
        cdr_name = next((k for k, v in active_cdrs.items() if pos in v), "unknown")
        for new_aa in AMINO_ACIDS:
            if new_aa == orig:
                continue
            mut = list(seq)
            mut[pos] = new_aa
            variants.append("".join(mut))
            reports.append([{
                "position": pos + 1,
                "original": orig,
                "mutant": new_aa,
                "cdr": cdr_name,
            }])
    return variants, reports


# ── Per-chain driver ──────────────────────────────────────────────────────────

def _process_chain(
    seq: str,
    chain_label: str,
    selected_cdrs: set[str],
    strategy: str,
    num_mutations: int,
    num_variants: int,
    scheme: str,
    rng: random.Random,
) -> tuple[list[str], list[list[dict]]]:
    _progress(f"Detecting CDR positions in V{chain_label} ({scheme})…")
    try:
        _ct, cdr_map = _get_cdr_positions(seq, scheme)
    except Exception as exc:
        _progress(f"⚠ abnumber failed for V{chain_label}: {exc}")
        return [], []

    active_cdrs = {k: v for k, v in cdr_map.items() if k in selected_cdrs}
    if not active_cdrs:
        _progress(f"  No selected CDRs found in V{chain_label} — skipping")
        return [], []

    for cdr, positions in sorted(active_cdrs.items()):
        span = f"{positions[0]+1}–{positions[-1]+1}" if positions else "?"
        _progress(f"  {cdr}: {len(positions)} residues (seq positions {span})")

    all_positions = sorted({pos for v in active_cdrs.values() for pos in v})

    if strategy == "saturation":
        _progress(f"  Saturation: {len(all_positions)} positions × 19 AAs = {len(all_positions)*19} variants")
        return _saturation_variants(seq, active_cdrs)

    # Collect Sapiens scores once for all variants
    sapiens_pos_scores: Optional[dict[int, dict[str, float]]] = None
    if strategy == "sapiens":
        _progress(f"  Loading Sapiens model for V{chain_label}…")
        sapiens_pos_scores = _sapiens_scores(seq, chain_label)
        if sapiens_pos_scores:
            _progress(f"  Sapiens scores ready ({len(sapiens_pos_scores)} positions)")
        else:
            _progress(f"  ⚠ Sapiens unavailable — using BLOSUM62 instead")

    _progress(f"  Generating {num_variants} variant(s) ({num_mutations} mutation(s) each)…")
    variants, reports = [], []
    for _ in range(num_variants):
        v, r = _make_variant(
            seq, all_positions, active_cdrs,
            strategy if sapiens_pos_scores is not None or strategy != "sapiens" else "blosum62",
            num_mutations, rng, sapiens_pos_scores,
        )
        variants.append(v)
        reports.append(r)

    return variants, reports


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    inputs = json.load(sys.stdin)

    heavy = str(inputs.get("heavy_chain", "") or "").strip()
    light = str(inputs.get("light_chain", "") or "").strip()

    if not heavy and not light:
        raise ValueError("At least one of heavy_chain or light_chain is required")

    # ── CDR region selection ───────────────────────────────────────────────────
    # Priority: cdr_target string (from RL agent) > individual bool inputs > legacy string
    _CDR_BOOL_MAP = {
        "CDR_H1": "cdr_h1",
        "CDR_H2": "cdr_h2",
        "CDR_H3": "cdr_h3",
        "CDR_L1": "cdr_l1",
        "CDR_L2": "cdr_l2",
        "CDR_L3": "cdr_l3",
    }
    selected_cdrs: set[str] = set()
    cdr_target = str(inputs.get("cdr_target", "") or "").strip()
    if cdr_target:
        # Normalize: "H3" / "CDR_H3" / "cdr_h3" → "CDR_H3"
        ct = cdr_target.upper().replace("-", "_")
        if not ct.startswith("CDR_"):
            ct = f"CDR_{ct}"
        selected_cdrs = {ct}
    elif any(k in inputs for k in _CDR_BOOL_MAP.values()):
        # At least one bool key present → use new format
        for cdr_name, input_key in _CDR_BOOL_MAP.items():
            val = inputs.get(input_key, False)
            # ParamPanel sends bools as Python bool or string "true"/"false"
            if isinstance(val, str):
                val = val.lower() == "true"
            if val:
                selected_cdrs.add(cdr_name)
    else:
        # Legacy fallback: comma-separated string
        cdr_str = str(inputs.get("cdr_regions", "CDR_H1,CDR_H2,CDR_H3")).strip()
        selected_cdrs = {r.strip() for r in cdr_str.split(",") if r.strip()}

    # Default to H1+H2+H3 if user unchecked everything
    if not selected_cdrs:
        selected_cdrs = {"CDR_H1", "CDR_H2", "CDR_H3"}
        _progress("⚠ No CDRs selected — defaulting to CDR_H1, CDR_H2, CDR_H3")

    strategy        = str(inputs.get("strategy", "blosum62")).strip().lower()
    num_mutations   = max(1, int(inputs.get("num_mutations", 3)))
    num_variants    = max(1, int(inputs.get("num_variants", 10)))
    scheme          = str(inputs.get("scheme", "imgt")).strip().lower()
    seed            = int(inputs.get("seed", 42))

    _progress(f"CDR Mutator | strategy={strategy} | cdrs={','.join(sorted(selected_cdrs))} "
              f"| mutations={num_mutations} | variants={num_variants} | scheme={scheme}")

    rng = random.Random(seed)

    heavy_variants: list[str] = []
    heavy_report:   list[list[dict]] = []
    light_variants: list[str] = []
    light_report:   list[list[dict]] = []

    # ── Heavy chain ────────────────────────────────────────────────────────────
    heavy_cdrs = {c for c in selected_cdrs if "H" in c}
    if heavy and heavy_cdrs:
        heavy_variants, heavy_report = _process_chain(
            heavy, "H", heavy_cdrs, strategy,
            num_mutations, num_variants, scheme, rng,
        )
    elif heavy and not heavy_cdrs:
        _progress("No heavy-chain CDRs selected — VH unchanged")
        heavy_variants = [heavy] * num_variants
        heavy_report   = [[] for _ in range(num_variants)]

    # ── Light chain ────────────────────────────────────────────────────────────
    light_cdrs = {c for c in selected_cdrs if "L" in c}
    if light and light_cdrs:
        light_variants, light_report = _process_chain(
            light, "L", light_cdrs, strategy,
            num_mutations, num_variants, scheme, rng,
        )
    elif light and not light_cdrs:
        _progress("No light-chain CDRs selected — VL unchanged")
        light_variants = [light] * num_variants
        light_report   = [[] for _ in range(num_variants)]

    n_h = len(heavy_variants)
    n_l = len(light_variants)

    summary = {
        "strategy":              strategy,
        "cdr_regions_targeted":  sorted(selected_cdrs),
        "num_heavy_variants":    n_h,
        "num_light_variants":    n_l,
        "mutations_per_variant": num_mutations if strategy != "saturation" else 1,
        "scheme":                scheme,
        "seed":                  seed if strategy != "saturation" else None,
    }

    _progress(f"Done — {n_h} VH variants, {n_l} VL variants")

    # ── Build output dict ──────────────────────────────────────────────────────
    n_out = max(n_h, n_l)
    sequences_variants = [
        {
            "vh": heavy_variants[i] if i < n_h else heavy,
            "vl": light_variants[i] if i < n_l else (light or None),
        }
        for i in range(n_out)
    ]
    result: dict = {
        "n": n_out,
        # Convenience single-sequence outputs (alias of variant_1)
        "heavy_chain": heavy_variants[0] if heavy_variants else (heavy or ""),
        "light_chain": light_variants[0] if light_variants else (light or ""),
        # Full libraries
        "heavy_chain_variants": heavy_variants,
        "light_chain_variants": light_variants,
        # Standard batch token — wire to any batch-aware downstream node
        "sequences": {"n": len(sequences_variants), "variants": sequences_variants},
        "mutation_report": {"heavy": heavy_report, "light": light_report},
        "summary": summary,
    }

    # ── Per-variant bundle outputs (variant_1 … variant_10) ───────────────────
    # Each carries {heavy_chain, light_chain} so it can be wired directly to any
    # downstream tool (ImmuneBuilder, AbMAP, BioPhi, etc.).
    # Unused slots are padded with None so the tool spec's declared outputs stay valid.
    _MAX_HANDLE_VARIANTS = 10
    for i in range(1, _MAX_HANDLE_VARIANTS + 1):
        idx = i - 1
        h = heavy_variants[idx] if idx < len(heavy_variants) else None
        l = light_variants[idx] if idx < len(light_variants) else None
        if h is not None or l is not None:
            result[f"variant_{i}"] = {
                "heavy_chain": h if h is not None else (heavy or ""),
                "light_chain": l if l is not None else (light or ""),
            }
        else:
            result[f"variant_{i}"] = None

    _progress(f"Variant bundles built — {min(n_out, _MAX_HANDLE_VARIANTS)} wirable handles")

    json.dump(result, sys.stdout)
    sys.stdout.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
