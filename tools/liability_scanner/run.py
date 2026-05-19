#!/usr/bin/env python
"""Liability Scanner — reads JSON from stdin, writes JSON to stdout.
Scans antibody VH/VL sequences for developability liability motifs.
No external dependencies; standard library only.
"""
import json
import re
import sys
from collections import Counter

# (name, regex_or_callable, description)
# Callable receives the full sequence and returns list of (start, end, matched_seq)
_MOTIFS = [
    ("N-glycosylation",  r"N[^P][ST]",     "N-linked glycosylation sequon (N-X-S/T, X≠P)"),
    ("Deamidation",      r"N[GS]",         "Deamidation hotspot (NG or NS)"),
    ("Isomerization",    r"D[GS]",         "Asp isomerization hotspot (DG or DS)"),
    ("Oxidation-Met",    r"M",             "Methionine oxidation risk"),
    ("Oxidation-Trp",    r"W",             "Tryptophan oxidation risk"),
    ("DP-cleavage",      r"DP",            "Asp-Pro peptide bond cleavage"),
    ("RGD-integrin",     r"RGD",           "RGD integrin-binding motif"),
    ("Lys-glycation",    r"K",             "Lysine glycation risk"),
]


def _scan_sequence(seq: str, chain_label: str) -> list[dict]:
    hits = []
    for motif_name, pattern, description in _MOTIFS:
        for m in re.finditer(pattern, seq):
            hits.append({
                "chain": chain_label,
                "motif": motif_name,
                "start": m.start() + 1,  # 1-based
                "end": m.end(),
                "sequence": m.group(0),
                "description": description,
            })
    return hits


def _check_unpaired_cys(seq: str, chain_label: str) -> list[dict]:
    count = seq.count("C")
    if count % 2 != 0:
        positions = [i + 1 for i, aa in enumerate(seq) if aa == "C"]
        return [{
            "chain": chain_label,
            "motif": "Unpaired-Cys",
            "start": positions[0] if positions else 0,
            "end": positions[-1] if positions else 0,
            "sequence": f"{count}×C",
            "description": f"Odd number of cysteines ({count}) — potential unpaired disulfide",
        }]
    return []


def main() -> None:
    inputs = json.load(sys.stdin)

    heavy = str(inputs.get("heavy_chain", "")).strip().upper()
    light = str(inputs.get("light_chain", "") or "").strip().upper()

    if not heavy:
        raise ValueError("heavy_chain is required")

    hits: list[dict] = []
    hits.extend(_scan_sequence(heavy, "VH"))
    hits.extend(_check_unpaired_cys(heavy, "VH"))

    if light:
        hits.extend(_scan_sequence(light, "VL"))
        hits.extend(_check_unpaired_cys(light, "VL"))

    counts: Counter = Counter(h["motif"] for h in hits)
    summary = {"total": len(hits), **dict(counts)}

    print(f"Scan complete: {len(hits)} liabilities found across {len(counts)} motif types.", file=sys.stderr)

    json.dump({
        "hits": hits,
        "summary": summary,
        "n_liabilities": len(hits),
    }, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)
