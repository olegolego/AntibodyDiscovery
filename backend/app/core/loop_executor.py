"""Loop executor helpers — shared utilities for the loop continuation logic in executor.py."""
import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.db.models import DockingResultRow, LoopRunRow
from app.db.session import AsyncSessionLocal
from app.models.pipeline import Pipeline
from app.models.run import NodeRunStatus, Run

log = logging.getLogger(__name__)

_cancelled_loops: set[str] = set()


def cancel_loop(loop_id: str) -> None:
    """Signal that a loop should stop before the next iteration starts."""
    _cancelled_loops.add(loop_id)
    # Also cancel the current iteration's run
    import asyncio
    from app.core.executor import request_cancel

    async def _try_cancel():
        async with AsyncSessionLocal() as db:
            row = await db.get(LoopRunRow, loop_id)
            if row:
                run_ids = json.loads(row.run_ids or "[]")
                if run_ids:
                    request_cancel(run_ids[-1])

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_try_cancel())
    except Exception:
        pass


async def _save_loop(
    loop_id: str,
    status: str,
    stop_reason: str | None,
    current_iteration: int,
    run_ids: list[str],
) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(LoopRunRow, loop_id)
        if row:
            row.status = status
            row.stop_reason = stop_reason
            row.current_iteration = current_iteration
            row.run_ids = json.dumps(run_ids)
            row.updated_at = datetime.utcnow()
            await db.commit()


def _patch_pipeline(
    pipeline: Pipeline,
    iteration: int,
    next_vh: str | None,
    next_vl: str | None,
) -> Pipeline:
    """Return a copy of the pipeline with sequence_input patched for the given iteration.

    loop_history is stored in LoopRunRow and injected by LoopAdapter at runtime.
    """
    data = pipeline.model_dump(mode="json")
    data = deepcopy(data)
    for node in data["nodes"]:
        if iteration > 0 and next_vh and node["tool"] in ("sequence_input", "sequence_db"):
            node["params"] = {**node.get("params", {}), "heavy_chain": next_vh, "light_chain": next_vl or ""}
    return Pipeline.model_validate(data)


def _extract_next_sequence(run: Run) -> tuple[str | None, str | None]:
    """Scan compute node outputs (last first) for next_heavy_chain / next_light_chain."""
    for node_run in reversed(list(run.nodes.values())):
        if node_run.status != NodeRunStatus.SUCCEEDED:
            continue
        outs = node_run.outputs or {}
        # Compute nodes return a dict under "result" key
        result = outs.get("result")
        if isinstance(result, dict):
            vh = result.get("next_heavy_chain") or result.get("heavy_chain")
            vl = result.get("next_light_chain") or result.get("light_chain")
            if vh:
                return str(vh), str(vl) if vl else None
        # Also check direct output keys
        vh = outs.get("next_heavy_chain")
        vl = outs.get("next_light_chain")
        if vh:
            return str(vh), str(vl) if vl else None
    return None, None


async def _build_history_entry(run_id: str, iteration: int, run: Run) -> dict[str, Any]:
    """Build a compact history entry from run results for injection into the next iteration."""
    entry: dict[str, Any] = {"iteration": iteration}

    # Pull VH/VL from any node that has them
    for node_run in run.nodes.values():
        outs = node_run.outputs or {}
        if outs.get("heavy_chain") and "vh" not in entry:
            entry["vh"] = outs["heavy_chain"]
        if outs.get("light_chain") and "vl" not in entry:
            entry["vl"] = outs["light_chain"]
        result = outs.get("result")
        if isinstance(result, dict):
            if result.get("next_heavy_chain") and "vh" not in entry:
                entry["vh"] = result["next_heavy_chain"]
            if result.get("next_light_chain") and "vl" not in entry:
                entry["vl"] = result["next_light_chain"]

    # Pull docking scores
    try:
        async with AsyncSessionLocal() as db:
            dock = (await db.execute(
                select(DockingResultRow)
                .where(DockingResultRow.run_id == run_id)
                .limit(1)
            )).scalar_one_or_none()
            if dock and dock.scores:
                scores = json.loads(dock.scores)
                for k, v in scores.items():
                    if isinstance(v, (int, float)):
                        entry[k] = v
    except Exception:
        pass

    return entry


