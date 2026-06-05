#!/usr/bin/env python3
"""Mutation Profiler subprocess entry point.

Reads JSON from stdin, writes JSON to stdout, progress to stderr.

Inputs:
  original  - fasta or plain AA string (wild-type reference)
  mutants   - JSON list of variant sequences; each entry may be:
              - a plain AA string
              - a FASTA string (with or without > header lines)
              - a dict with a "sequence" key

Outputs:
  absolute_frequencies  - {str(pos_idx): {AA: count, ...}, ...}  (includes original)
  relative_frequencies  - {str(pos_idx): {AA: float, ...}, ...}
  mutation_summary      - {n_sequences, n_positions, top_mutations: [...]}
"""
import json
import sys
from collections import defaultdict


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean_sequence(raw: str) -> str:
    """Strip FASTA headers, whitespace, lowercase; return plain uppercase AA string."""
    lines = []
    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue  # FASTA header
        lines.append(stripped.upper())
    return "".join(lines)


def _parse_mutant_entry(entry) -> str:
    """Coerce a mutant list entry to a plain AA string."""
    if isinstance(entry, dict):
        raw = entry.get("sequence", "")
    else:
        raw = str(entry)
    return _clean_sequence(raw)


def _run(inputs: dict) -> dict:
    # -- Parse original sequence --------------------------------------------------
    original_raw = str(inputs.get("original", "")).strip()
    if not original_raw:
        raise ValueError("'original' sequence is required")
    original = _clean_sequence(original_raw)
    if not original:
        raise ValueError("'original' sequence is empty after cleaning")

    n_positions = len(original)
    _progress(f"Original sequence length: {n_positions}")

    # -- Parse mutant sequences --------------------------------------------------
    mutants_raw = inputs.get("mutants", [])
    if isinstance(mutants_raw, str):
        # Caller may have passed JSON-encoded string
        mutants_raw = json.loads(mutants_raw)
    if not isinstance(mutants_raw, list):
        raise ValueError("'mutants' must be a JSON list")

    mutant_seqs = []
    for i, entry in enumerate(mutants_raw):
        seq = _parse_mutant_entry(entry)
        if not seq:
            _progress(f"  Warning: mutant #{i} is empty, skipping")
            continue
        if len(seq) != n_positions:
            raise ValueError(
                f"Mutant #{i} length {len(seq)} != original length {n_positions}"
            )
        mutant_seqs.append(seq)

    _progress(f"Processing {len(mutant_seqs)} variant sequences + original")

    # -- Compute per-position AA counts (include original) -----------------------
    all_seqs = [original] + mutant_seqs
    n_total = len(all_seqs)

    # absolute_frequencies[pos] = {AA: count}
    absolute: dict[int, dict[str, int]] = {}
    for pos in range(n_positions):
        counts: dict[str, int] = defaultdict(int)
        for seq in all_seqs:
            aa = seq[pos]
            counts[aa] += 1
        absolute[pos] = dict(counts)

    # relative_frequencies[pos] = {AA: probability}
    relative: dict[int, dict[str, float]] = {}
    for pos, counts in absolute.items():
        total = sum(counts.values())
        relative[pos] = {aa: round(c / total, 6) for aa, c in counts.items()}

    # -- Mutation summary --------------------------------------------------------
    # Find positions where at least one mutant differs from WT
    top_mutations = []
    for pos in range(n_positions):
        wt_aa = original[pos]
        pos_counts = absolute[pos]
        for aa, count in pos_counts.items():
            if aa == wt_aa:
                continue
            freq = relative[pos][aa]
            top_mutations.append({
                "pos": pos,
                "wt": wt_aa,
                "mut": aa,
                "freq": freq,
                "count": count,
            })

    # Sort by frequency descending, keep top 50
    top_mutations.sort(key=lambda x: x["freq"], reverse=True)
    top_mutations = top_mutations[:50]

    mutation_summary = {
        "n_sequences": n_total,
        "n_positions": n_positions,
        "n_mutated_positions": len({m["pos"] for m in top_mutations}),
        "top_mutations": top_mutations,
    }

    _progress(
        f"Done — {mutation_summary['n_mutated_positions']} mutated positions, "
        f"{len(top_mutations)} distinct mutations in top-50"
    )

    # JSON keys must be strings
    return {
        "absolute_frequencies": {str(k): v for k, v in absolute.items()},
        "relative_frequencies": {str(k): v for k, v in relative.items()},
        "mutation_summary": mutation_summary,
        "original": original,  # pass-through so mutation_composer downstream can find the WT
    }


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
