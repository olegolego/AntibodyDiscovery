"""WebSocket endpoint for live Compute node code execution."""
import asyncio
import io
import json
import sys
import traceback
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


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

        await _exec_with_stream(code, injected, ws)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
