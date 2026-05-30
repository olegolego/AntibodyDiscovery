"""Loop run API — status, cancel, and continue endpoints.

Loops are started automatically when a pipeline containing a Loop node is
submitted via POST /api/runs/.  These endpoints allow the frontend to poll
status and cancel an in-progress loop campaign.
"""
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.core.loop_executor import cancel_loop, _cancelled_loops, _extract_next_sequence, _patch_pipeline
from app.db.models import LoopRunRow, RunRow
from app.db.session import AsyncSessionLocal
from app.models.pipeline import Pipeline
from app.models.run import Run

router = APIRouter()


@router.get("/")
async def list_loops():
    """List all loop runs, most recent first."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(LoopRunRow).order_by(LoopRunRow.created_at.desc()).limit(50)
        )).scalars().all()
    # Fetch latest run status in one pass for all loops
    latest_run_statuses: dict[str, str] = {}
    try:
        all_latest_ids = [
            json.loads(r.run_ids or "[]")[-1]
            for r in rows
            if json.loads(r.run_ids or "[]")
        ]
        if all_latest_ids:
            run_rows = (await db.execute(
                select(RunRow).where(RunRow.id.in_(all_latest_ids))
            )).scalars().all()
            latest_run_statuses = {rr.id: rr.status for rr in run_rows}
    except Exception:
        pass

    result = []
    for row in rows:
        run_ids = json.loads(row.run_ids or "[]")
        latest_run_id = run_ids[-1] if run_ids else None
        latest_run_status = latest_run_statuses.get(latest_run_id) if latest_run_id else None
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
            "latest_run_id": latest_run_id,
            "latest_run_status": latest_run_status,
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
    # Deduplicate by iteration: keep the entry with the best (lowest) score per iteration.
    score_history: list[dict] = []
    try:
        raw_history = json.loads(row.loop_history or "[]")
        best_by_iter: dict[int, dict] = {}
        for entry in raw_history:
            vh = str(entry.get("vh") or "")
            haddock_scores: dict = entry.get("haddock_scores") or {}
            numeric_scores = [v for v in haddock_scores.values() if isinstance(v, (int, float))]
            best = min(numeric_scores) if numeric_scores else entry.get("haddock_score")
            iter_num = entry.get("iteration", 0)
            record = {
                "iteration": iter_num,
                "vh_prefix": vh[:25],
                "vh_cdr3": vh[-24:-10] if len(vh) > 34 else vh[-14:],
                "best_score": best,
                "scores_by_rank": haddock_scores,
            }
            existing = best_by_iter.get(iter_num)
            if existing is None:
                best_by_iter[iter_num] = record
            else:
                # Keep the entry with the better (lower) score
                if best is not None and (existing["best_score"] is None or best < existing["best_score"]):
                    best_by_iter[iter_num] = record
        score_history = [best_by_iter[k] for k in sorted(best_by_iter)]
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


@router.post("/{loop_id}/continue/")
async def continue_loop_run(loop_id: str):
    """Resume a cancelled or succeeded loop from where it stopped.

    Picks up the next sequence from the last completed run, rebuilds the
    accumulated dataset from stored loop history, and fires the next iteration.
    """
    from app.core.executor import create_run, execute_run

    async with AsyncSessionLocal() as db:
        loop_row = await db.get(LoopRunRow, loop_id)
        if loop_row is None:
            raise HTTPException(status_code=404, detail="Loop run not found")

        # Allow continuing a "running" loop that is stuck — i.e. its latest run
        # has already reached a terminal state (failed/cancelled) but the loop
        # status was never updated because the old code didn't handle failures.
        if loop_row.status == "running":
            run_ids_check = json.loads(loop_row.run_ids or "[]")
            last_run_row = await db.get(RunRow, run_ids_check[-1]) if run_ids_check else None
            last_run_active = last_run_row and last_run_row.status in ("queued", "running")
            if last_run_active:
                raise HTTPException(status_code=400, detail="Loop is already running")
            # Treat stuck-running as continuable; fall through
        elif loop_row.status not in ("cancelled", "succeeded"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot continue a loop with status '{loop_row.status}'",
            )

    # Clear any stale in-memory cancel flag so the next iteration can proceed.
    _cancelled_loops.discard(loop_id)

    loop_history = json.loads(loop_row.loop_history or "[]")
    run_ids = json.loads(loop_row.run_ids or "[]")
    pipeline = Pipeline.model_validate(json.loads(loop_row.pipeline_snapshot))

    # Use current_iteration (tracks the next iteration index correctly) rather than
    # len(run_ids), which can drift if duplicate runs were created for the same iteration.
    next_iter = loop_row.current_iteration
    max_iterations = loop_row.max_iterations

    # Continuing past the original budget — double the iteration limit and update
    # the stored pipeline snapshot so _do_continue_loop reads the new limit on
    # every subsequent iteration (not just the first one).
    updated_snapshot: str | None = None
    if next_iter >= max_iterations:
        max_iterations = next_iter + max_iterations
    # Always patch max_iterations into loop nodes so the created run's pipeline has
    # the authoritative limit (the pipeline_snapshot may have a stale value).
    for node in pipeline.nodes:
        if node.tool in ("loop_start", "loop_end", "loop"):
            node.params = {**node.params, "max_iterations": max_iterations}
    updated_snapshot = json.dumps(pipeline.model_dump(mode="json"))

    # Get next sequence from the last completed run's outputs.
    next_vh, next_vl = None, None
    if run_ids:
        async with AsyncSessionLocal() as db:
            last_run_row = await db.get(RunRow, run_ids[-1])
            if last_run_row:
                last_run = Run.model_validate_json(last_run_row.data)
                next_vh, next_vl = _extract_next_sequence(last_run)
    # Fallback to next_vh stored in the last history entry.
    if not next_vh and loop_history:
        next_vh = loop_history[-1].get("next_vh")

    next_pipeline = _patch_pipeline(pipeline, next_iter, next_vh, next_vl, loop_history)
    next_run = await create_run(next_pipeline, loop_id=loop_id, iteration=next_iter)

    async with AsyncSessionLocal() as db:
        loop_row = await db.get(LoopRunRow, loop_id)
        if loop_row:
            all_run_ids = json.loads(loop_row.run_ids or "[]")
            if next_run.id not in all_run_ids:
                all_run_ids.append(next_run.id)
            loop_row.run_ids = json.dumps(all_run_ids)
            loop_row.current_iteration = next_iter
            loop_row.status = "running"
            loop_row.stop_reason = None
            loop_row.max_iterations = max_iterations
            if updated_snapshot:
                loop_row.pipeline_snapshot = updated_snapshot
            loop_row.updated_at = datetime.utcnow()
            await db.commit()

    asyncio.ensure_future(execute_run(next_run.id))
    return {"ok": True, "run_id": next_run.id, "iteration": next_iter}
