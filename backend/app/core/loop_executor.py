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


def _build_accumulated_dataset(loop_history: list[dict]) -> dict | None:
    """Build accumulated {embeddings, scores_rank_1..4} dict from all history entries.

    Each entry must have been built by _build_history_entry which captures:
      - vh: sequence identifier
      - embedding: AbMAP 512d vector
      - haddock_scores: {rank_1: float, rank_2: float, ...}
    """
    if not loop_history:
        return None
    accumulated: dict = {"embeddings": {}}
    for entry in loop_history:
        seq_id = entry.get("vh") or f"iter_{entry.get('iteration', 0)}"
        emb = entry.get("embedding")
        if emb and isinstance(emb, list) and emb:
            accumulated["embeddings"][seq_id] = emb
        for rank_key, score in (entry.get("haddock_scores") or {}).items():
            if isinstance(score, (int, float)):
                acc_key = f"scores_{rank_key}"   # "rank_1" → "scores_rank_1"
                accumulated.setdefault(acc_key, {})[seq_id] = float(score)
    # Drop empty sub-dicts
    accumulated = {k: v for k, v in accumulated.items() if v}
    return accumulated if accumulated.get("embeddings") else None


def _patch_pipeline(
    pipeline: Pipeline,
    iteration: int,
    next_vh: str | None,
    next_vl: str | None,
    loop_history: list[dict] | None = None,
) -> Pipeline:
    """Return a copy of the pipeline with sequence_input patched for the given iteration.

    Also injects accumulated_dataset into any rcc_mlde nodes from the full
    loop_history so they retrain on ALL evaluated sequences, not just the current round.
    """
    data = pipeline.model_dump(mode="json")
    data = deepcopy(data)

    accumulated = _build_accumulated_dataset(loop_history or [])

    for node in data["nodes"]:
        # Patch input sequences
        if iteration > 0 and next_vh and node["tool"] in ("sequence_input", "sequence_db", "loop_start"):
            node["params"] = {**node.get("params", {}), "heavy_chain": next_vh, "light_chain": next_vl or ""}

        # Inject accumulated dataset into rcc_mlde / dnn_mlde training nodes
        if node["tool"] in ("rcc_mlde", "dnn_mlde") and accumulated:
            node["params"] = {**node.get("params", {}), "accumulated_dataset": accumulated}

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


_ABMAP_TOOLS  = {"abmap"}
_ESM_TOOLS    = {"esm_embedding"}
_HADDOCK_TOOLS = {"haddock3"}

# Heuristic: extract the rank suffix from a node_id for HADDOCK3 nodes.
# e.g. "haddock_r1" → "rank_1", "haddock3_rank2" → "rank_2", "h_2" → "rank_2"
def _haddock_rank(node_id: str) -> str | None:
    import re
    m = re.search(r"[r_](\d)$", node_id)
    if m:
        return f"rank_{m.group(1)}"
    return None


async def _build_history_entry(run_id: str, iteration: int, run: Run) -> dict[str, Any]:
    """Build a compact history entry from run results for injection into the next iteration.

    Captures per-iteration:
      - vh / vl (sequence)
      - embedding (AbMAP 512d vector for the evaluated sequence)
      - haddock_scores: {"rank_1": float, "rank_2": float, ...} (per conformation)
      - haddock_score (legacy single-score compat)
    These are consumed by _patch_pipeline to build the accumulated_dataset for rcc_mlde.
    """
    entry: dict[str, Any] = {"iteration": iteration}

    pipeline = run.pipeline_snapshot or {}
    # Map node_id → tool for quick lookup
    snap_tool: dict[str, str] = {
        n["id"]: n["tool"] for n in pipeline.get("nodes", [])
    }

    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        outs = node_run.outputs or {}
        tool  = snap_tool.get(node_id, "")

        # ── VH / VL ───────────────────────────────────────────────────
        # Priority: loop_start > loop > abmap > other tools (NOT cdr_mutator which
        # outputs a *mutated* sequence — we want the sequence that was actually
        # evaluated by HADDOCK and embedded by AbMAP for the training data).
        _CDR_MUTATION_TOOLS = {"cdr_mutator"}
        if outs.get("heavy_chain") and "vh" not in entry and tool not in _CDR_MUTATION_TOOLS:
            entry["vh"] = outs["heavy_chain"]
        if outs.get("light_chain") and "vl" not in entry and tool not in _CDR_MUTATION_TOOLS:
            entry["vl"] = outs["light_chain"]
        result = outs.get("result")
        if isinstance(result, dict):
            if result.get("next_heavy_chain") and "vh" not in entry:
                entry["vh"] = result["next_heavy_chain"]
            if result.get("next_light_chain") and "vl" not in entry:
                entry["vl"] = result["next_light_chain"]

        # ── AbMAP embedding ────────────────────────────────────────────
        # Prefer the "train" AbMAP node (embeds the evaluated sequence) over the
        # "cand" node (embeds CDR mutants for scoring). Fall back to any AbMAP node.
        if tool in _ABMAP_TOOLS:
            emb = outs.get("embedding")
            if isinstance(emb, list) and emb and isinstance(emb[0], (int, float)):
                is_train = "train" in node_id.lower() and "cand" not in node_id.lower()
                if is_train or "embedding" not in entry:
                    entry["embedding"] = emb

        # ── HADDOCK3 scores per rank ───────────────────────────────────
        if tool in _HADDOCK_TOOLS:
            scores = outs.get("scores")
            if isinstance(scores, dict):
                score_val = scores.get("score")
                if isinstance(score_val, (int, float)):
                    rank_key = _haddock_rank(node_id) or "rank_1"
                    entry.setdefault("haddock_scores", {})[rank_key] = float(score_val)
                    # Legacy compat
                    if "haddock_score" not in entry:
                        entry["haddock_score"] = float(score_val)

    # Also pull docking scores from DB (existing path)
    try:
        async with AsyncSessionLocal() as db:
            dock = (await db.execute(
                select(DockingResultRow)
                .where(DockingResultRow.run_id == run_id)
                .limit(1)
            )).scalar_one_or_none()
            if dock and dock.scores:
                db_scores = json.loads(dock.scores)
                for k, v in db_scores.items():
                    if isinstance(v, (int, float)) and k not in entry:
                        entry[k] = v
    except Exception:
        pass

    return entry


