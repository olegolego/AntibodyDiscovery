#!/usr/bin/env python3
"""Mutation Composer subprocess entry point.

Reads JSON from stdin, writes JSON to stdout, progress to stderr.

Inputs:
  original       - fasta or plain AA string (wild-type reference)
  frequencies    - per-position AA frequency dict from MutationProfiler
                   ({str(pos): {AA: count_or_prob, ...}, ...})
  num_sequences  - int, how many candidates to generate (default 10)
  mode           - "weighted_random" | "top1" | "uniform_random" (default "weighted_random")
  max_mutations  - int, max positions mutated per candidate (default 3)

Outputs:
  sequences   - list of generated AA strings
  candidates  - [{sequence: str, mutations: [{pos, wt, mut}, ...]}, ...]
"""
import json
import random
import sys


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean_sequence(raw: str) -> str:
    """Strip FASTA headers, whitespace; return plain uppercase AA string."""
    lines = []
    for line in raw.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            continue
        lines.append(stripped.upper())
    return "".join(lines)


def _normalize_weights(counts: dict[str, float]) -> tuple[list[str], list[float]]:
    """Return (aas, weights) with weights summing to 1.0."""
    aas = list(counts.keys())
    raw = [max(0.0, float(counts[aa])) for aa in aas]
    total = sum(raw)
    if total == 0:
        # Fallback: uniform
        weights = [1.0 / len(aas)] * len(aas)
    else:
        weights = [w / total for w in raw]
    return aas, weights


def _sample_aa(pos_freq: dict[str, float], wt_aa: str, mode: str) -> str:
    """Sample an amino acid for a position according to mode, excluding WT."""
    # Remove WT so we always mutate
    freq_no_wt = {aa: v for aa, v in pos_freq.items() if aa != wt_aa}
    if not freq_no_wt:
        return wt_aa  # no mutation possible at this position

    if mode == "top1":
        return max(freq_no_wt, key=lambda aa: float(freq_no_wt[aa]))
    elif mode == "uniform_random":
        return random.choice(list(freq_no_wt.keys()))
    else:  # weighted_random (default)
        aas, weights = _normalize_weights(freq_no_wt)
        return random.choices(aas, weights=weights, k=1)[0]


def _run(inputs: dict) -> dict:
    # -- Parse original sequence -------------------------------------------------
    original_raw = str(inputs.get("original", "")).strip()
    if not original_raw:
        raise ValueError("'original' sequence is required")
    original = _clean_sequence(original_raw)
    if not original:
        raise ValueError("'original' sequence is empty after cleaning")

    n_positions = len(original)
    _progress(f"Original sequence length: {n_positions}")

    # -- Parse frequencies -------------------------------------------------------
    frequencies_raw = inputs.get("frequencies", {})
    if isinstance(frequencies_raw, str):
        frequencies_raw = json.loads(frequencies_raw)
    if not isinstance(frequencies_raw, dict):
        raise ValueError("'frequencies' must be a dict (from MutationProfiler output)")

    # Normalize keys to int for internal use
    frequencies: dict[int, dict[str, float]] = {}
    for k, v in frequencies_raw.items():
        try:
            pos = int(k)
        except (ValueError, TypeError):
            continue
        if isinstance(v, dict):
            frequencies[pos] = {str(aa): float(cnt) for aa, cnt in v.items()}

    # -- Parameters --------------------------------------------------------------
    num_sequences = int(inputs.get("num_sequences", 10))
    mode = str(inputs.get("mode", "weighted_random")).strip().lower()
    max_mutations = int(inputs.get("max_mutations", 3))

    if mode not in ("weighted_random", "top1", "uniform_random"):
        raise ValueError(f"Unknown mode '{mode}'. Use: weighted_random, top1, uniform_random")

    _progress(
        f"Generating {num_sequences} candidates | mode={mode} | max_mutations={max_mutations}"
    )

    # Identify positions that have any non-WT variation
    mutable_positions = []
    for pos in range(n_positions):
        if pos not in frequencies:
            continue
        wt_aa = original[pos]
        pos_freq = frequencies[pos]
        has_variation = any(aa != wt_aa and float(v) > 0 for aa, v in pos_freq.items())
        if has_variation:
            mutable_positions.append(pos)

    _progress(f"Mutable positions with variation: {len(mutable_positions)}")

    if not mutable_positions:
        _progress("Warning: no mutable positions found — returning original sequence copies")
        sequences = [original] * num_sequences
        candidates = [{"sequence": original, "mutations": []} for _ in range(num_sequences)]
        return {"sequences": sequences, "candidates": candidates}

    # -- Generate candidates -----------------------------------------------------
    sequences = []
    candidates = []

    for i in range(num_sequences):
        # Randomly select how many positions to mutate (1 to max_mutations)
        k = random.randint(1, min(max_mutations, len(mutable_positions)))
        selected_positions = random.sample(mutable_positions, k)

        seq_list = list(original)
        mutations = []

        for pos in selected_positions:
            wt_aa = original[pos]
            pos_freq = frequencies.get(pos, {})
            if not pos_freq:
                continue
            new_aa = _sample_aa(pos_freq, wt_aa, mode)
            if new_aa != wt_aa:
                seq_list[pos] = new_aa
                mutations.append({"pos": pos, "wt": wt_aa, "mut": new_aa})

        candidate_seq = "".join(seq_list)
        sequences.append(candidate_seq)
        candidates.append({"sequence": candidate_seq, "mutations": mutations})

        if (i + 1) % 100 == 0:
            _progress(f"  Generated {i + 1}/{num_sequences} candidates")

    _progress(f"Done — {len(sequences)} candidate sequences generated")

    return {
        "sequences": sequences,
        "candidates": candidates,
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
