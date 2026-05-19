#!/usr/bin/env python3
"""Filter node subprocess entry point.

Reads JSON from stdin: all upstream variables + operation params.
Writes JSON to stdout: {sequences, scores, count, removed_count, error}
"""
import io
import json
import sys
import traceback


def _parse_fasta(fasta_str: str) -> dict[str, str]:
    seqs: dict[str, str] = {}
    name: str | None = None
    parts: list[str] = []
    for line in fasta_str.splitlines():
        line = line.strip()
        if line.startswith(">"):
            if name is not None:
                seqs[name] = "".join(parts)
            name = line[1:].split()[0]
            parts = []
        elif line:
            parts.append(line)
    if name is not None:
        seqs[name] = "".join(parts)
    return seqs


def _build_fasta(names: list[str], seqs_by_name: dict[str, str]) -> str:
    lines: list[str] = []
    for name in names:
        seq = seqs_by_name.get(name, "")
        if seq:
            lines.append(f">{name}")
            lines.append(seq)
    return "\n".join(lines)


def _run(inputs: dict) -> dict:
    code = str(inputs.get("code", "") or "").strip()

    if code:
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        import collections
        import json as _json
        import math
        import re as _re

        import numpy as np

        excluded = {"code", "score_var", "sequence_var", "min_score", "max_score"}
        namespace = {
            "np": np,
            "math": math,
            "re": _re,
            "json": _json,
            "collections": collections,
            **{k: v for k, v in inputs.items() if k not in excluded},
        }
        error = None
        try:
            exec(compile(code, "<filter>", "exec"), namespace)  # noqa: S102
        except Exception:
            error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout

        raw = namespace.get("result")
        if error or raw is None:
            return {"sequences": "", "scores": {}, "count": 0, "removed_count": 0,
                    "stdout": captured.getvalue(), "error": error}

        # Normalise result: list of names, dict {name: score}, or FASTA string
        if isinstance(raw, str) and raw.strip().startswith(">"):
            kept_seqs = _parse_fasta(raw)
            return {
                "sequences": raw,
                "scores": {},
                "count": len(kept_seqs),
                "removed_count": 0,
                "stdout": captured.getvalue(),
                "error": None,
            }
        if isinstance(raw, dict):
            score_var = str(inputs.get("score_var", "") or "").strip()
            sequence_var = str(inputs.get("sequence_var", "") or "").strip()
            seqs_by_name = _parse_fasta(inputs.get(sequence_var, "") or "") if sequence_var else {}
            total = len(inputs.get(score_var, {}) or {})
            kept_names = list(raw.keys())
            return {
                "sequences": _build_fasta(kept_names, seqs_by_name),
                "scores": raw,
                "count": len(kept_names),
                "removed_count": max(0, total - len(kept_names)),
                "stdout": captured.getvalue(),
                "error": None,
            }
        if isinstance(raw, list):
            score_var = str(inputs.get("score_var", "") or "").strip()
            sequence_var = str(inputs.get("sequence_var", "") or "").strip()
            all_scores = inputs.get(score_var, {}) or {}
            seqs_by_name = _parse_fasta(inputs.get(sequence_var, "") or "") if sequence_var else {}
            kept_names = [str(x) for x in raw]
            return {
                "sequences": _build_fasta(kept_names, seqs_by_name),
                "scores": {k: all_scores[k] for k in kept_names if k in all_scores},
                "count": len(kept_names),
                "removed_count": max(0, len(all_scores) - len(kept_names)),
                "stdout": captured.getvalue(),
                "error": None,
            }
        return {"sequences": "", "scores": {}, "count": 0, "removed_count": 0,
                "stdout": captured.getvalue(), "error": f"Unexpected result type: {type(raw).__name__}"}

    # Threshold-based filtering
    score_var = str(inputs.get("score_var", "") or "").strip()
    sequence_var = str(inputs.get("sequence_var", "") or "").strip()
    min_score = inputs.get("min_score")
    max_score = inputs.get("max_score")

    if not score_var:
        return {"error": "score_var is required when not using custom code"}

    all_scores = inputs.get(score_var)
    if not isinstance(all_scores, dict):
        return {"error": f"score_var '{score_var}' must be a dict, got {type(all_scores).__name__}"}

    seqs_by_name = _parse_fasta(inputs.get(sequence_var, "") or "") if sequence_var else {}

    kept: dict[str, float] = {}
    for name, score in all_scores.items():
        try:
            s = float(score)
        except (TypeError, ValueError):
            continue
        if min_score is not None and s < float(min_score):
            continue
        if max_score is not None and s > float(max_score):
            continue
        kept[name] = s

    removed = len(all_scores) - len(kept)
    return {
        "sequences": _build_fasta(list(kept.keys()), seqs_by_name),
        "scores": kept,
        "count": len(kept),
        "removed_count": removed,
        "error": None,
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
