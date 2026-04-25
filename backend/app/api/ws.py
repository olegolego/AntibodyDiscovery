import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.events import manager
from app.core.executor import _slim_outputs
from app.db.session import AsyncSessionLocal
from app.db.models import RunRow

router = APIRouter()


@router.websocket("/runs/{run_id}")
async def run_ws(run_id: str, websocket: WebSocket) -> None:
    await manager.connect(run_id, websocket)
    try:
        # Send current state immediately on connect so the client gets status
        # even if it connects after the run has started or finished.
        async with AsyncSessionLocal() as db:
            row = await db.get(RunRow, run_id)
            if row:
                run_data = json.loads(row.data)
                for nr in run_data.get("nodes", {}).values():
                    if nr.get("outputs"):
                        nr["outputs"] = _slim_outputs(nr["outputs"])
                await websocket.send_json({"type": "run_update", "run": run_data})

        # Keep alive — client drives reconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(run_id, websocket)
