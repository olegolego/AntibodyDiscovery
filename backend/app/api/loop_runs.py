"""Loop run API — status and cancel endpoints.

Loops are started automatically when a pipeline containing a Loop node is
submitted via POST /api/runs/.  These endpoints allow the frontend to poll
status and cancel an in-progress loop campaign.
"""
import json

from fastapi import APIRouter, HTTPException

from app.core.loop_executor import cancel_loop
from app.db.models import LoopRunRow
from app.db.session import AsyncSessionLocal

router = APIRouter()


@router.get("/{loop_id}/")
async def get_loop(loop_id: str):
    async with AsyncSessionLocal() as db:
        row = await db.get(LoopRunRow, loop_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Loop run not found")
        return {
            "loop_id": row.id,
            "pipeline_id": row.pipeline_id,
            "max_iterations": row.max_iterations,
            "current_iteration": row.current_iteration,
            "status": row.status,
            "stop_reason": row.stop_reason,
            "run_ids": json.loads(row.run_ids or "[]"),
            "created_at": row.created_at.isoformat(),
        }


@router.post("/{loop_id}/cancel/")
async def cancel_loop_run(loop_id: str):
    async with AsyncSessionLocal() as db:
        row = await db.get(LoopRunRow, loop_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Loop run not found")
    cancel_loop(loop_id)
    return {"ok": True}
