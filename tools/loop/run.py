#!/usr/bin/env python3
"""Loop node subprocess entry point.

Same execution model as compute/run.py — reads JSON from stdin and
writes JSON to stdout.  loop_history and loop_iteration are pre-injected
by the LoopAdapter before the subprocess is launched.
"""
import io
import json
import sys
import traceback


def _run(inputs: dict) -> dict:
    code = str(inputs.get("code", ""))
    injected = {k: v for k, v in inputs.items() if k != "code"}

    captured = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured

    namespace = dict(injected)
    error = None
    try:
        exec(compile(code, "<loop>", "exec"), namespace)  # noqa: S102
    except Exception:
        error = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    result = namespace.get("result")
    # Hoist next_heavy_chain / next_light_chain to top-level for easy extraction
    if isinstance(result, dict):
        top = {
            "next_heavy_chain": result.get("next_heavy_chain"),
            "next_light_chain": result.get("next_light_chain"),
        }
    else:
        top = {
            "next_heavy_chain": namespace.get("next_heavy_chain"),
            "next_light_chain": namespace.get("next_light_chain"),
        }

    return {
        **top,
        "result": result,
        "stdout": captured.getvalue(),
        "error": error,
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
