#!/usr/bin/env python
"""DeepSP tool runner — reads JSON from stdin, writes JSON to stdout.
Calculates SAP, surface charge, and surface hydrophobicity from VH/VL sequences.
Implements core DeepSP descriptors (MIT) using ANARCI for CDR extraction.
Requires: anarci, numpy  (conda env: deepsp)
"""
import json
import sys

# Kyte-Doolittle hydrophobicity scale
_KD = {
    "A": 1.8,  "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8,  "K": -3.9, "M": 1.9,  "F": 2.8,  "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3,  "V": 4.2,
}

# Residue charge at physiological pH
_CHARGE = {
    "R": +1, "K": +1, "H": +0.1,   # positive
    "D": -1, "E": -1,               # negative
}

# Chothia CDR definitions (loop names → (start, end) inclusive residue numbers)
_CDR_CHOTHIA_H = {
    "H1": (26, 32), "H2": (52, 56), "H3": (95, 102),
}
_CDR_CHOTHIA_L = {
    "L1": (24, 34), "L2": (50, 56), "L3": (89, 97),
}


def _extract_cdrs_anarci(seq: str, chain_type: str) -> dict[str, str]:
    """Use ANARCI to number the chain, then extract CDR residues."""
    from anarci import anarci as _anarci

    results, _, _ = _anarci([(f"{chain_type}1", seq)], scheme="chothia", output=False)
    if not results or not results[0]:
        return {}

    # results[0][0] is a tuple (numbered_list, score, ...) — take index 0
    numbered = results[0][0][0]  # list of ((pos, ins_code), aa)
    # Build position → aa map (use first occurrence per position)
    pos_map: dict[int, str] = {}
    for (pos, _ins), aa in numbered:
        if aa != "-" and pos not in pos_map:
            pos_map[pos] = aa

    cdr_defs = _CDR_CHOTHIA_H if chain_type == "H" else _CDR_CHOTHIA_L
    cdrs = {}
    for loop, (start, end) in cdr_defs.items():
        residues = "".join(pos_map.get(p, "") for p in range(start, end + 1))
        cdrs[loop] = residues
    return cdrs


def _sap_score(cdr_residues: dict[str, str]) -> float:
    """SAP ≈ sum of hydrophobicity of CDR residues with KD > 0 (exposed patch proxy)."""
    total = 0.0
    for seq in cdr_residues.values():
        for aa in seq:
            h = _KD.get(aa, 0.0)
            if h > 0:
                total += h
    return round(total, 4)


def _surface_charge(seq: str) -> float:
    return round(sum(_CHARGE.get(aa, 0) for aa in seq), 4)


def _surface_hydrophobicity(cdr_residues: dict[str, str]) -> float:
    all_cdr = "".join(cdr_residues.values())
    if not all_cdr:
        return 0.0
    return round(sum(_KD.get(aa, 0.0) for aa in all_cdr) / len(all_cdr), 4)


def main() -> None:
    inputs = json.load(sys.stdin)

    heavy = str(inputs.get("heavy_chain", "")).strip().upper()
    light = str(inputs.get("light_chain", "") or "").strip().upper()

    if not heavy:
        raise ValueError("heavy_chain is required")

    print("Numbering VH with ANARCI (Chothia)…", file=sys.stderr, flush=True)
    vh_cdrs = _extract_cdrs_anarci(heavy, "H")
    vl_cdrs: dict[str, str] = {}
    if light:
        print("Numbering VL with ANARCI (Chothia)…", file=sys.stderr, flush=True)
        vl_cdrs = _extract_cdrs_anarci(light, "L")

    all_cdrs = {**vh_cdrs, **vl_cdrs}
    full_seq = heavy + light

    sap = _sap_score(all_cdrs)
    charge = _surface_charge(full_seq)
    hydro = _surface_hydrophobicity(all_cdrs)

    print(f"SAP={sap}, charge={charge}, hydrophobicity={hydro}", file=sys.stderr)

    report = {
        "vh_cdrs": vh_cdrs,
        "vl_cdrs": vl_cdrs,
        "per_cdr_sap": {
            loop: _sap_score({loop: seq}) for loop, seq in all_cdrs.items()
        },
    }

    json.dump({
        "sap_score": sap,
        "surface_charge": charge,
        "surface_hydrophobicity": hydro,
        "cdr_residues": all_cdrs,
        "report": report,
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)
