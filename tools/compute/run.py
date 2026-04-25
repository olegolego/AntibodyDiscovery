#!/usr/bin/env python3
"""Compute node subprocess entry point.
Reads JSON from stdin: {"code": str, "inputs": {var_name: value, ...}}
Writes JSON to stdout: {"result": <any>, "stdout": str, "error": str|null}
"""
import io
import json
import sys
import traceback


def _run(inputs: dict) -> dict:
    code = str(inputs.get("code", ""))
    injected = {k: v for k, v in inputs.items() if k != "code"}

    # Capture stdout
    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    namespace = dict(injected)
    error = None
    try:
        exec(compile(code, "<compute>", "exec"), namespace)  # noqa: S102
    except Exception:
        error = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    return {
        "result": namespace.get("result"),
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
