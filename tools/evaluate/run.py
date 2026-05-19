#!/usr/bin/env python3
"""Evaluate node subprocess entry point.

Reads JSON from stdin: all upstream variables + operation params.
Writes JSON to stdout: {scores, summary, sorted_names, error}
"""
import io
import json
import math
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


def _statistics(scores: dict[str, float]) -> dict:
    if not scores:
        return {"mean": None, "std": None, "min": None, "max": None, "count": 0,
                "best_name": None, "best_score": None, "worst_name": None, "worst_score": None}

    vals = [float(v) for v in scores.values()]
    n = len(vals)
    mean = sum(vals) / n
    variance = sum((v - mean) ** 2 for v in vals) / n
    std = math.sqrt(variance)
    best_name = max(scores, key=lambda k: float(scores[k]))
    worst_name = min(scores, key=lambda k: float(scores[k]))

    return {
        "mean": round(mean, 6),
        "std": round(std, 6),
        "min": round(min(vals), 6),
        "max": round(max(vals), 6),
        "count": n,
        "best_name": best_name,
        "best_score": round(float(scores[best_name]), 6),
        "worst_name": worst_name,
        "worst_score": round(float(scores[worst_name]), 6),
    }


def _run(inputs: dict) -> dict:
    code = str(inputs.get("code", "") or "").strip()

    if code:
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        import collections
        import json as _json
        import re as _re

        import numpy as np

        excluded = {"code", "score_var", "sequence_var"}
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
            exec(compile(code, "<evaluate>", "exec"), namespace)  # noqa: S102
        except Exception:
            error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout

        raw = namespace.get("result")
        if error or raw is None:
            return {"scores": {}, "summary": {}, "sorted_names": [],
                    "stdout": captured.getvalue(), "error": error}

        if isinstance(raw, dict) and "scores" in raw:
            scores = raw["scores"]
            summary = raw.get("summary") or _statistics(scores)
            sorted_names = sorted(scores, key=lambda k: float(scores[k]), reverse=True)
            return {
                "scores": scores,
                "summary": summary,
                "sorted_names": sorted_names,
                "stdout": captured.getvalue(),
                "error": None,
            }
        if isinstance(raw, dict):
            # Treat the whole result as a scores dict
            summary = _statistics(raw)
            sorted_names = sorted(raw, key=lambda k: float(raw[k]), reverse=True)
            return {
                "scores": raw,
                "summary": summary,
                "sorted_names": sorted_names,
                "stdout": captured.getvalue(),
                "error": None,
            }
        return {"scores": {}, "summary": {}, "sorted_names": [],
                "stdout": captured.getvalue(),
                "error": f"result must be a dict, got {type(raw).__name__}"}

    # Auto path: summarise the score_var
    score_var = str(inputs.get("score_var", "") or "").strip()

    if not score_var:
        return {"error": "score_var is required when not using custom code"}

    all_scores = inputs.get(score_var)
    if not isinstance(all_scores, dict):
        return {"error": f"score_var '{score_var}' must be a dict, got {type(all_scores).__name__}"}

    float_scores = {}
    for k, v in all_scores.items():
        try:
            float_scores[k] = float(v)
        except (TypeError, ValueError):
            pass

    summary = _statistics(float_scores)
    sorted_names = sorted(float_scores, key=float_scores.__getitem__, reverse=True)

    return {
        "scores": float_scores,
        "summary": summary,
        "sorted_names": sorted_names,
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
