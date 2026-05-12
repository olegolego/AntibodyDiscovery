"""WebSocket endpoint for live Compute node code execution + AI code generation."""
import asyncio
import io
import json
import os
import re
import sys
import traceback
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

router = APIRouter()

# ── AI code generation ────────────────────────────────────────────────────────

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
_MODEL = "claude-sonnet-4-6"

_SYSTEM_PROMPT = """\
You are a Python code generator embedded in an antibody design pipeline.
The user will describe a computation in plain language. You write Python 3.11
code that performs that computation and assigns the final result to a variable
named `result`.

Rules:
- Always assign the final answer to `result`.
- Standard library and numpy (as np), scipy, json, math, re, collections are available.
- PDB data is a plain string in PDB format. Sequence data is a plain amino-acid string.
- Do NOT use print() for the result — only assign `result`.
- Return ONLY the Python code. No markdown fences, no explanation, no comments."""


class _VarInfo(BaseModel):
    name: str
    type: str


class GenerateCodeRequest(BaseModel):
    prompt: str
    variables: list[_VarInfo] = []


def _extract_code(text: str) -> str:
    fenced = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text.strip()


@router.post("/generate")
async def generate_code(body: GenerateCodeRequest) -> dict[str, str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not set on the server.",
        )

    var_lines = "\n".join(f"  {v.name}: {v.type}" for v in body.variables) or "  (none)"
    user_msg = f"Available variables:\n{var_lines}\n\nRequest: {body.prompt}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": _MODEL,
                "max_tokens": 1024,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_msg}],
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {resp.text}")

    code = _extract_code(resp.json()["content"][0]["text"])
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
