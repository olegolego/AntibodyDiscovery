"""WebSocket endpoint for live Compute node code execution + AI code generation."""
import asyncio
import io
import json
import os
import re
import sys
import traceback
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter()

# ── AI code generation ────────────────────────────────────────────────────────

# Static persona + rules — stays the same for every request.
_PROMPT_PERSONA = """\
You are an expert bioinformatics software developer embedded in an antibody \
design pipeline. You have deep knowledge of structural biology, protein \
sequences, and computational tools used in antibody engineering (AlphaFold, \
RFdiffusion, ProteinMPNN, HADDOCK, ImmuneBuilder, AbLang, AbMAP, etc.).\
"""

_PROMPT_RULES = """\
## Coding rules
- Assign the final result to a variable named `result`.
- numpy (as np), scipy, json, math, re, collections are available alongside \
the Python 3.11 standard library.
- Sequences are plain amino-acid strings (single-letter codes).
- PDB structures are plain strings in PDB format.
- Numeric scores and embeddings are Python lists or floats.
- Do NOT use print() — only assign `result`.
- Return ONLY executable Python code. No markdown fences, no prose, \
no comments.\
"""

# Dynamic section — injected per-request with the live variable list.
_PROMPT_VARS_TEMPLATE = """\
## Variables available in this environment
These values come from upstream nodes connected to this Compute block and are \
already bound in your Python environment — you do not need to import or define them:

{var_block}\
"""


class _VarInfo(BaseModel):
    name: str
    type: str


class GenerateCodeRequest(BaseModel):
    prompt: str
    variables: list[_VarInfo] = []


def _build_system_prompt(variables: list[_VarInfo]) -> str:
    if variables:
        var_block = "\n".join(f"  {v.name}: {v.type}" for v in variables)
    else:
        var_block = "  (no upstream variables connected yet)"
    vars_section = _PROMPT_VARS_TEMPLATE.format(var_block=var_block)
    return f"{_PROMPT_PERSONA}\n\n{vars_section}\n\n{_PROMPT_RULES}"


def _extract_code(text: str) -> str:
    fenced = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text.strip()


@router.post("/generate")
async def generate_code(body: GenerateCodeRequest) -> dict[str, str]:
    system = _build_system_prompt(body.variables)

    # Strip ANTHROPIC_API_KEY from the child env so the CLI uses its own OAuth
    # session rather than the (invalid for CLI use) API key from backend/.env.
    child_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print",
            "--system-prompt", system,
            body.prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=child_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Claude CLI timed out (60s)")
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="'claude' CLI not found on PATH")

    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace"))[:400]
        raise HTTPException(status_code=502, detail=f"Claude CLI error: {err}")

    code = _extract_code(stdout.decode("utf-8", errors="replace"))
    return {"code": code}


async def _exec_with_stream(
    code: str,
    injected: dict[str, Any],
    ws: WebSocket,
) -> None:
    """Execute code in a thread, streaming stdout line-by-line via WebSocket."""
    loop = asyncio.get_event_loop()

    # Queue for streaming output
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def _run() -> None:
        buf = io.StringIO()
        original_write = buf.write

        class _StreamingIO(io.StringIO):
            def write(self, s: str) -> int:
                n = original_write(s)
                if s:
                    asyncio.run_coroutine_threadsafe(
                        queue.put({"type": "stdout", "text": s}), loop
                    )
                return n

        namespace = dict(injected)
        streaming_out = _StreamingIO()
        old_stdout = sys.stdout
        sys.stdout = streaming_out

        error = None
        try:
            exec(compile(code, "<compute>", "exec"), namespace)  # noqa: S102
        except Exception:
            error = traceback.format_exc()
        finally:
            sys.stdout = old_stdout

        result = namespace.get("result")
        asyncio.run_coroutine_threadsafe(
            queue.put(
                {
                    "type": "done",
                    "result": _safe_json(result),
                    "error": error,
                }
            ),
            loop,
        )

    task = loop.run_in_executor(None, _run)

    while True:
        try:
            msg = await asyncio.wait_for(queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            if task.done():
                break
            continue
        await ws.send_json(msg)
        if msg["type"] == "done":
            break

    # Drain any remaining messages
    while not queue.empty():
        await ws.send_json(queue.get_nowait())


def _safe_json(value: Any) -> Any:
    """Ensure value is JSON-serialisable; fall back to repr."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


@router.websocket("/execute")
async def compute_execute(ws: WebSocket) -> None:
    """
    WebSocket protocol:
      client → {"code": str, "inputs": {var: value, ...}}
      server → {"type": "stdout", "text": str}
               {"type": "done",   "result": any, "error": str|null}
               {"type": "error",  "message": str}   (protocol-level errors)
    """
    await ws.accept()
    try:
        raw = await ws.receive_text()
        payload = json.loads(raw)
        code = str(payload.get("code", ""))
        injected = {k: v for k, v in payload.get("inputs", {}).items()}

        if not code.strip():
            await ws.send_json({"type": "done", "result": None, "error": None})
            return

        try:
            await asyncio.wait_for(_exec_with_stream(code, injected, ws), timeout=30.0)
        except asyncio.TimeoutError:
            try:
                await ws.send_json({"type": "done", "result": None, "error": "Execution timed out (30s limit)"})
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
