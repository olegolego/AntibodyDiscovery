#!/usr/bin/env python3
"""Loop objective node — user-defined composite loss/objective for active learning loops.

Same execution model as compute: reads JSON from stdin, writes JSON to stdout.
"""
import io
import json
import math
import sys
import traceback


def _run(inputs: dict) -> dict:
    code = str(inputs.get("code", "")).strip()
    if not code:
        raise ValueError("code is required for loop_objective node")

    injected = {k: v for k, v in inputs.items() if k != "code"}

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    import collections
    import re as _re
    import json as _json

    try:
        import numpy as np
    except ImportError:
        np = None  # type: ignore

    namespace = {
        "math": math,
        "re": _re,
        "json": _json,
        "collections": collections,
        **({"np": np} if np is not None else {}),
        **injected,
    }
    error = None
    try:
        exec(compile(code, "<loop_objective>", "exec"), namespace)  # noqa: S102
    except Exception:
        error = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    result = namespace.get("result")
    obj_score = None
    if isinstance(result, dict):
        obj_score = result.get("objective_score")
    elif isinstance(result, (int, float)):
        obj_score = float(result)
        result = {"objective_score": obj_score}

    if obj_score is None and error is None:
        error = (
            "loop_objective code did not set result['objective_score']. "
            "Assign a numeric value: result = {'objective_score': <float>}"
        )

    return {
        "objective_score": obj_score,
        "result": result,
        "stdout": captured.getvalue(),
        "error": error,
        "metadata": {"injected_vars": list(injected.keys())},
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
