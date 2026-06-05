"""WebSocket endpoint streaming MD frames for one sim_id.

Protocol
  client → server: {"type": "start", "spec": <SystemSpec>}  ·  {"type": "cancel"}
  server → client: init · frame · done · error · cancelled   (see md/runner.py)

The socket is registered with the shared ConnectionManager keyed by sim_id, so
the runner's ``manager.broadcast(sim_id, ...)`` reaches it. The run executes as a
background task while the receive loop stays free to handle a "cancel" message.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import manager
from app.db.models import MDSimulationRow
from app.db.session import AsyncSessionLocal
from app.md.runner import request_cancel, run_simulation
from app.md.spec import SystemSpec

log = logging.getLogger(__name__)
router = APIRouter()


async def _persist_status(sim_id: str, status: str, summary: dict | None = None) -> None:
    """Best-effort update of a saved simulation's status (sim_id may be ephemeral)."""
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(MDSimulationRow, sim_id)
            if row is None:
                return
            row.status = status
            if summary is not None:
                row.summary = json.dumps(summary)
            await db.commit()
    except Exception:  # noqa: BLE001 — status persistence must never break the stream
        pass


@router.websocket("/ws/md-ground/{sim_id}")
async def md_ground_ws(sim_id: str, websocket: WebSocket) -> None:
    await manager.connect(sim_id, websocket)
    run_task: asyncio.Task | None = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON", "step": 0})
                continue

            mtype = msg.get("type")
            if mtype == "start":
                if run_task and not run_task.done():
                    request_cancel(sim_id)
                    await run_task
                try:
                    spec = SystemSpec.model_validate(msg.get("spec", {}))
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "message": f"Invalid spec: {exc}", "step": 0})
                    continue

                async def _run(spec=spec):
                    await _persist_status(sim_id, "running")
                    try:
                        summary = await run_simulation(sim_id, spec)
                        await _persist_status(sim_id, "done", summary)
                    except Exception:  # noqa: BLE001 — already broadcast to client
                        await _persist_status(sim_id, "error")

                run_task = asyncio.ensure_future(_run())

            elif mtype == "cancel":
                request_cancel(sim_id)

    except WebSocketDisconnect:
        request_cancel(sim_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("MD WS error for %s: %s", sim_id, exc)
    finally:
        request_cancel(sim_id)
        manager.disconnect(sim_id, websocket)
