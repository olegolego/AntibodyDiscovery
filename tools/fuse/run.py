#!/usr/bin/env python3
"""Fuse — creates fusion proteins by concatenating sequences with flexible linkers.

Reads JSON from stdin:
  {
    sequences: list[str],           # AA sequences to concatenate (in order)
    linker: str,                    # linker motif (e.g. "GSG")
    linker_lengths: list[str],      # one "min-max" range per junction
    name: str                       # base name for output IDs
  }

Writes JSON to stdout:
  {
    fusions: [{id, sequence, linker_composition}],
    n_fusions: int
  }

Writes progress to stderr.

Generates the cartesian product of all linker-repeat counts across junctions.
E.g. 3 sequences + linker_lengths=["0-3","0-3"] → 4×4 = 16 constructs.
"""
import itertools
import json
import sys


def _parse_range(range_str: str) -> range:
    """Parse "min-max" into range(min, max+1). Also accept a plain int."""
    s = str(range_str).strip()
    if "-" in s:
        parts = s.split("-", 1)
        lo, hi = int(parts[0]), int(parts[1])
    else:
        lo = hi = int(s)
    if lo > hi:
        raise ValueError(f"Invalid range '{range_str}': min > max")
    return range(lo, hi + 1)


def _run(inputs: dict) -> dict:
    # ---- parse sequences ----
    raw_seqs = inputs.get("sequences", [])
    if isinstance(raw_seqs, str):
        try:
            raw_seqs = json.loads(raw_seqs)
        except json.JSONDecodeError as exc:
            return {"error": f"'sequences' is not valid JSON: {exc}"}

    if not isinstance(raw_seqs, list) or len(raw_seqs) < 2:
        return {"error": "'sequences' must be a JSON list with at least 2 entries"}

    sequences: list[str] = [str(s).strip().upper() for s in raw_seqs]
    n_seqs = len(sequences)
    n_junctions = n_seqs - 1

    # ---- parse linker ----
    linker = str(inputs.get("linker", "GSG")).strip().upper()

    # ---- parse linker_lengths ----
    raw_lengths = inputs.get("linker_lengths", [f"0-{n_junctions}"] * n_junctions)
    if isinstance(raw_lengths, str):
        try:
            raw_lengths = json.loads(raw_lengths)
        except json.JSONDecodeError as exc:
            return {"error": f"'linker_lengths' is not valid JSON: {exc}"}

    if not isinstance(raw_lengths, list):
        return {"error": "'linker_lengths' must be a JSON list"}

    # If user provides exactly one range for multiple junctions, broadcast it
    if len(raw_lengths) == 1 and n_junctions > 1:
        raw_lengths = raw_lengths * n_junctions

    if len(raw_lengths) != n_junctions:
        return {
            "error": (
                f"'linker_lengths' must have exactly {n_junctions} entries "
                f"(one per junction between {n_seqs} sequences), got {len(raw_lengths)}"
            )
        }

    try:
        ranges = [_parse_range(r) for r in raw_lengths]
    except ValueError as exc:
        return {"error": str(exc)}

    # ---- base name ----
    name = str(inputs.get("name", "fusion")).strip() or "fusion"

    print(
        f"Fuse: {n_seqs} sequences, linker='{linker}', junctions={n_junctions}",
        file=sys.stderr,
        flush=True,
    )
    print(f"  Length ranges: {[str(r) for r in raw_lengths]}", file=sys.stderr, flush=True)

    total = 1
    for r in ranges:
        total *= len(r)
    print(f"  Generating {total} fusion variant(s)...", file=sys.stderr, flush=True)

    fusions: list[dict] = []

    for combo in itertools.product(*ranges):
        # combo is a tuple of repeat counts, one per junction
        # Build fused sequence
        parts = [sequences[0]]
        for i, n_repeats in enumerate(combo):
            parts.append(linker * n_repeats)
            parts.append(sequences[i + 1])
        fused_seq = "".join(parts)

        # Build ID: {name}_L{n0}_{n1}_...
        suffix = "_".join(str(c) for c in combo)
        fusion_id = f"{name}_L{suffix}"

        fusions.append({
            "id": fusion_id,
            "sequence": fused_seq,
            "linker_composition": list(combo),
        })

    print(f"Fuse done: {len(fusions)} variant(s) generated.", file=sys.stderr, flush=True)

    return {
        "fusions": fusions,
        "n_fusions": len(fusions),
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
