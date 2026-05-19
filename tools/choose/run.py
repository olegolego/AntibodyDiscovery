#!/usr/bin/env python3
"""Choose node subprocess entry point.

Reads JSON from stdin: all upstream variables + operation params.
Writes JSON to stdout: {sequence, name, score, sequences, ranking, error}
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
    strategy = str(inputs.get("strategy", "top_score"))
    n = max(1, int(inputs.get("n", 1) or 1))

    if strategy == "custom_code":
        code = str(inputs.get("code", "")).strip()
        if not code:
            return {"error": "custom_code strategy requires a non-empty code field"}

        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured

        import collections
        import json as _json
        import math
        import re as _re

        import numpy as np

        excluded = {"code", "strategy", "n", "score_var", "sequence_var"}
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
            exec(compile(code, "<choose>", "exec"), namespace)  # noqa: S102
        except Exception:
            error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout

        raw = namespace.get("result")
        if isinstance(raw, dict):
            return {
                "sequence": raw.get("sequence", ""),
                "name": raw.get("name", ""),
                "score": raw.get("score"),
                "sequences": _build_fasta([raw]) if raw.get("sequence") else "",
                "ranking": [],
                "stdout": captured.getvalue(),
                "error": error,
            }
        return {
            "sequence": str(raw) if raw is not None else "",
            "name": "",
            "score": None,
            "sequences": "",
            "ranking": [],
            "stdout": captured.getvalue(),
            "error": error,
        }

    # Auto strategies: top_score / bottom_score
    score_var = str(inputs.get("score_var", "") or "").strip()
    sequence_var = str(inputs.get("sequence_var", "") or "").strip()

    if not score_var:
        return {"error": "score_var is required for top_score / bottom_score strategy"}

    scores = inputs.get(score_var)
    if scores is None:
        available = [k for k in inputs if not k.startswith("_") and k not in
                     ("strategy", "n", "score_var", "sequence_var", "code")]
        return {
            "error": (
                f"score_var '{score_var}' not found in inputs. "
                f"Available variables: {available}"
            )
        }
    if not isinstance(scores, dict):
        return {"error": f"score_var '{score_var}' must be a dict, got {type(scores).__name__}"}
    if not scores:
        return {"error": f"score_var '{score_var}' is empty — no sequences to choose from"}

    reverse = strategy != "bottom_score"
    try:
        ranked_names = sorted(scores.keys(), key=lambda k: float(scores[k]), reverse=reverse)
    except (TypeError, ValueError) as exc:
        return {"error": f"Cannot sort scores: {exc}"}

    seqs_by_name: dict[str, str] = {}
    if sequence_var:
        fasta = inputs.get(sequence_var, "")
        if isinstance(fasta, str) and fasta.strip():
            seqs_by_name = _parse_fasta(fasta)

    ranking = [
        {
            "rank": i + 1,
            "name": name,
            "sequence": seqs_by_name.get(name, ""),
            "score": float(scores[name]),
        }
        for i, name in enumerate(ranked_names)
    ]

    top = ranking[:n]

    return {
        "sequence": top[0]["sequence"] if top else "",
        "name": top[0]["name"] if top else "",
        "score": top[0]["score"] if top else None,
        "sequences": _build_fasta(top),
        "ranking": ranking,
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
