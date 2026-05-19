"""Loop run API — status and cancel endpoints.

Loops are started automatically when a pipeline containing a Loop node is
submitted via POST /api/runs/.  These endpoints allow the frontend to poll
status and cancel an in-progress loop campaign.
"""
import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.loop_executor import cancel_loop
from app.db.models import LoopRunRow
from app.db.session import AsyncSessionLocal

router = APIRouter()


@router.get("/")
async def list_loops():
    """List all loop runs, most recent first."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(LoopRunRow).order_by(LoopRunRow.created_at.desc()).limit(50)
        )).scalars().all()
    result = []
    for row in rows:
        run_ids = json.loads(row.run_ids or "[]")
        # Extract best score and best iteration from loop_history for card display
        best_score: float | None = None
        best_iter: int | None = None
        score_count = 0
        try:
            raw_history = json.loads(row.loop_history or "[]")
            for entry in raw_history:
                haddock_scores: dict = entry.get("haddock_scores") or {}
                numeric = [v for v in haddock_scores.values() if isinstance(v, (int, float))]
                entry_best = min(numeric) if numeric else entry.get("haddock_score")
                if entry_best is not None:
                    score_count += 1
                    if best_score is None or entry_best < best_score:
                        best_score = entry_best
                        best_iter = entry.get("iteration")
        except Exception:
            pass
        result.append({
            "loop_id": row.id,
            "pipeline_id": row.pipeline_id,
            "max_iterations": row.max_iterations,
            "current_iteration": row.current_iteration,
            "status": row.status,
            "stop_reason": row.stop_reason,
            "run_ids_count": len(run_ids),
            "latest_run_id": run_ids[-1] if run_ids else None,
            "created_at": row.created_at.isoformat(),
            "best_score": best_score,
            "best_iter": best_iter,
            "score_count": score_count,
        })
    return result


@router.get("/{loop_id}/")
async def get_loop(loop_id: str):
    async with AsyncSessionLocal() as db:
        row = await db.get(LoopRunRow, loop_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Loop run not found")

    # Build a compact score history from the stored loop_history JSON.
    # Each entry: {iteration, vh_prefix, best_score, scores_by_rank}
    score_history: list[dict] = []
    try:
        raw_history = json.loads(row.loop_history or "[]")
        for entry in raw_history:
            vh = str(entry.get("vh") or "")
            haddock_scores: dict = entry.get("haddock_scores") or {}
            # Best score = minimum (most negative) across available ranks
            numeric_scores = [v for v in haddock_scores.values() if isinstance(v, (int, float))]
            best = min(numeric_scores) if numeric_scores else entry.get("haddock_score")
            score_history.append({
                "iteration": entry.get("iteration", 0),
                "vh_prefix": vh[:25],
                "vh_cdr3": vh[-24:-10] if len(vh) > 34 else vh[-14:],  # CDR3 region
                "best_score": best,
                "scores_by_rank": haddock_scores,
            })
    except Exception:
        pass

    return {
        "loop_id": row.id,
        "pipeline_id": row.pipeline_id,
        "max_iterations": row.max_iterations,
        "current_iteration": row.current_iteration,
        "status": row.status,
        "stop_reason": row.stop_reason,
        "run_ids": json.loads(row.run_ids or "[]"),
        "created_at": row.created_at.isoformat(),
        "score_history": score_history,
    }


@router.post("/{loop_id}/cancel/")
async def cancel_loop_run(loop_id: str):
    async with AsyncSessionLocal() as db:
        row = await db.get(LoopRunRow, loop_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Loop run not found")
    cancel_loop(loop_id)
    return {"ok": True}
