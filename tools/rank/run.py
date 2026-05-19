#!/usr/bin/env python3
"""Rank node subprocess entry point.

Reads JSON from stdin: all upstream variables + operation params.
Writes JSON to stdout: {sequences, ranking, scores, error}
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


def _build_fasta(items: list[dict]) -> str:
    lines: list[str] = []
    for item in items:
        if item.get("sequence"):
            lines.append(f">{item['name']}")
            lines.append(item["sequence"])
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

        excluded = {"code", "score_var", "sequence_var", "order", "top_k"}
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
            exec(compile(code, "<rank>", "exec"), namespace)  # noqa: S102
        except Exception:
            error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout

        raw = namespace.get("result")
        if error or raw is None:
            return {"sequences": "", "ranking": [], "scores": {},
                    "stdout": captured.getvalue(), "error": error}

        # Normalise result: list of {name, score} or {name, score, sequence}
        if not isinstance(raw, list):
            return {"sequences": "", "ranking": [], "scores": {},
                    "stdout": captured.getvalue(),
                    "error": f"result must be a list, got {type(raw).__name__}"}

        ranking = []
        for i, item in enumerate(raw):
            if isinstance(item, dict):
                ranking.append({
                    "rank": i + 1,
                    "name": str(item.get("name", "")),
                    "sequence": str(item.get("sequence", "")),
                    "score": float(item["score"]) if "score" in item else None,
                })
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                ranking.append({"rank": i + 1, "name": str(item[0]),
                                 "sequence": "", "score": float(item[1])})

        return {
            "sequences": _build_fasta(ranking),
            "ranking": ranking,
            "scores": {r["name"]: r["score"] for r in ranking},
            "stdout": captured.getvalue(),
            "error": None,
        }

    # Auto sort
    score_var = str(inputs.get("score_var", "") or "").strip()
    sequence_var = str(inputs.get("sequence_var", "") or "").strip()
    order = str(inputs.get("order", "descending") or "descending")
    top_k = int(inputs.get("top_k", 0) or 0)

    if not score_var:
        return {"error": "score_var is required when not using custom code"}

    all_scores = inputs.get(score_var)
    if not isinstance(all_scores, dict):
        return {"error": f"score_var '{score_var}' must be a dict, got {type(all_scores).__name__}"}

    seqs_by_name = _parse_fasta(inputs.get(sequence_var, "") or "") if sequence_var else {}

    try:
        reverse = order != "ascending"
        sorted_names = sorted(all_scores.keys(), key=lambda k: float(all_scores[k]), reverse=reverse)
    except (TypeError, ValueError) as exc:
        return {"error": f"Cannot sort scores: {exc}"}

    if top_k > 0:
        sorted_names = sorted_names[:top_k]

    ranking = [
        {
            "rank": i + 1,
            "name": name,
            "sequence": seqs_by_name.get(name, ""),
            "score": float(all_scores[name]),
        }
        for i, name in enumerate(sorted_names)
    ]

    return {
        "sequences": _build_fasta(ranking),
        "ranking": ranking,
        "scores": {r["name"]: r["score"] for r in ranking},
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
