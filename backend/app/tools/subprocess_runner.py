"""Run a tool in its own venv via subprocess.

The tool's run.py reads JSON from stdin and writes JSON to stdout.
Progress lines written to stderr are forwarded live via on_log callback.

Every invocation is persisted to /tmp/pdp-runs/<run_id>_<tool_id>_raw.json
so results survive even if the analysis pipeline fails or the server restarts.
"""
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_RUN_LOG_DIR = Path(os.getenv("PDP_RUN_LOG_DIR", "/tmp/pdp-runs"))
_RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _persist_subprocess_result(
    run_id: str | None,
    tool_id: str,
    stdout_raw: bytes,
    stderr_lines: list[str],
    returncode: int,
) -> None:
    """Write raw subprocess output to disk. Never raises."""
    if not run_id:
        return
    try:
        path = _RUN_LOG_DIR / f"{run_id}_{tool_id}_raw.json"
        record = {
            "run_id": run_id,
            "tool_id": tool_id,
            "returncode": returncode,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "stdout": stdout_raw.decode(errors="replace"),
            "stderr_tail": stderr_lines[-200:],
        }
        path.write_text(json.dumps(record, indent=2))
    except Exception:
        pass

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TOOLS_DIR = _REPO_ROOT / "tools"

# run_id -> active asyncio Process (for cancellation)
_active_procs: dict[str, asyncio.subprocess.Process] = {}


def kill_subprocess(run_id: str) -> None:
    """Kill the active subprocess for a run, if any."""
    proc = _active_procs.pop(run_id, None)
    if proc is not None:
        try:
            proc.kill()
        except Exception:
            pass


async def run_tool_subprocess(
    tool_id: str,
    inputs: dict[str, Any],
    timeout: int = 7200,
    on_log: Any | None = None,
    run_id: str | None = None,
    python_path: str | None = None,
) -> dict[str, Any]:
    """Invoke tools/<tool_id>/run.py in its own venv (non-blocking).

    stderr lines are forwarded one-by-one via on_log (if provided) as they arrive.
    Pass run_id to enable cancellation via kill_subprocess().
    Pass python_path to override the default tool .venv (e.g. use sys.executable for
    tools that run in the backend environment rather than an isolated venv).
    Raises RuntimeError on non-zero exit or JSON decode failure.
    """
    tool_dir = TOOLS_DIR / tool_id
    runner = tool_dir / "run.py"

    if python_path is not None:
        python = Path(python_path)
    else:
        python = tool_dir / ".venv" / "bin" / "python"
        if not python.exists():
            raise FileNotFoundError(
                f"Tool venv not found: {python}\n"
                f"Run: python3.10 -m venv tools/{tool_id}/.venv && "
                f"tools/{tool_id}/.venv/bin/pip install -r tools/{tool_id}/requirements.txt"
            )

    if not runner.exists():
        raise FileNotFoundError(f"Tool runner not found: {runner}")

    proc = await asyncio.create_subprocess_exec(
        str(python), "-u", str(runner),   # -u = unbuffered stdout/stderr
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PYTHONUNBUFFERED": "1", **__import__("os").environ},
    )

    if run_id is not None:
        _active_procs[run_id] = proc

    stdin_bytes = json.dumps(inputs).encode()
    proc.stdin.write(stdin_bytes)
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_lines: list[str] = []

    async def _drain_stderr() -> None:
        assert proc.stderr is not None
        async for raw in proc.stderr:
            line = raw.decode().rstrip()
            if not line:
                continue
            stderr_lines.append(line)
            if on_log is not None:
                await on_log(line)

    try:
        stdout_data, _ = await asyncio.wait_for(
            asyncio.gather(
                proc.stdout.read(),
                _drain_stderr(),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"{tool_id} timed out after {timeout}s")
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    finally:
        if run_id is not None:
            _active_procs.pop(run_id, None)

    await proc.wait()

    # Persist raw output immediately — before any parsing that could throw
    _persist_subprocess_result(run_id, tool_id, stdout_data, stderr_lines, proc.returncode)

    if proc.returncode != 0:
        error_msg = ""
        try:
            payload = json.loads(stdout_data)
            error_msg = payload.get("error", "")
        except Exception:
            pass
        if not error_msg:
            error_msg = "\n".join(stderr_lines[-20:]) or stdout_data.decode()[:2000]
        raise RuntimeError(f"{tool_id} failed (exit {proc.returncode}): {error_msg}")

    try:
        return json.loads(stdout_data)
    except json.JSONDecodeError as exc:
        preview = stdout_data.decode()[:500]
        raise RuntimeError(
            f"{tool_id} run.py returned invalid JSON: {exc}\nOutput preview: {preview}"
        ) from exc
