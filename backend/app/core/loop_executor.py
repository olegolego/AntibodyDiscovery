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

        # Inject accumulated dataset into rcc_mlde / dnn_mlde / custom_dnn training nodes
        if node["tool"] in ("rcc_mlde", "dnn_mlde", "custom_dnn") and accumulated:
            node["params"] = {**node.get("params", {}), "accumulated_dataset": accumulated}

        # Inject rolling policy_state into rl_designer nodes
        accumulated_rl = _build_accumulated_rl_state(loop_history or [])
        if node["tool"] == "rl_designer" and accumulated_rl:
            node["params"] = {**node.get("params", {}), "policy_state": accumulated_rl}

    return Pipeline.model_validate(data)


def _pick_fallback_sequence(loop_history: list[dict]) -> tuple[str | None, str | None]:
    """Return the first saved fallback sequence that hasn't been evaluated yet.

    Fallback sequences are stored in history entries as ``fallback_sequences``
    (a list of top-K candidates from the ML node beyond the one that was
    selected by loop_end).  We scan history newest-first so we prefer
    candidates from the most recent model fit.
    """
    tested_vhs = {e.get("vh") for e in loop_history if e.get("vh")}
    for entry in reversed(loop_history):
        for seq in entry.get("fallback_sequences") or []:
            if seq and seq not in tested_vhs:
                return str(seq), None
    return None, None


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


_ABMAP_TOOLS   = {"abmap"}
_ESM_TOOLS     = {"esm_embedding", "ablang", "cheap_embedding", "aa_chem_embedding", "aa_onehot_embedding"}
_HADDOCK_TOOLS = {"haddock3"}
# Any tool that produces an embedding — used for history capture
_EMBEDDING_TOOLS = _ABMAP_TOOLS | _ESM_TOOLS

# Float output keys that count as a "score" for any non-HADDOCK scoring node.
# A node named with a _r{N} suffix (e.g. deepsp_r1, netsolp_r2, biophi_r3) and
# outputting one of these keys will be captured into haddock_scores for the DNN.
_GENERIC_SCORE_KEYS = (
    "score", "sap_score", "heavy_solubility", "heavy_usability",
    "n_liabilities", "heavy_mutations", "humanness_score",
    "solubility_score", "stability_score",
)


# Heuristic: extract the rank suffix from a node_id.
# e.g. "haddock_r1" → "rank_1", "deepsp_r2" → "rank_2", "netsolp_r3" → "rank_3"
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
        - embedding (AbMAP/ESM/AbLang vector for the evaluated sequence)
        - haddock_scores: {"rank_1": float, ...} — from HADDOCK nodes OR from any node
        whose ID ends with _r{N} (e.g. deepsp_r1, netsolp_r2, biophi_r3) and
        outputs a recognized numeric score key.
        - haddock_score (legacy single-score compat)
    These are consumed by _patch_pipeline to build the accumulated_dataset for dnn_mlde/rcc_mlde.
    """
    entry: dict[str, Any] = {"iteration": iteration}

    pipeline = run.pipeline_snapshot or {}
    # Map node_id → tool for quick lookup
    snap_tool: dict[str, str] = {
        n["id"]: n["tool"] for n in pipeline.get("nodes", [])
    }

    # VH capture — two passes:
    # Pass 1 — primary: capture the EVALUATED sequence from loop_start / sequence_input.
    #           This is the sequence that was actually docked/scored in this iteration
    #           and whose embedding+score belong together for training.
    #           Also capture next_heavy_chain from loop_end as next_vh (for reference only).
    # Pass 2 — fallback: any node (except cdr_mutator) that outputs heavy_chain.
    _CDR_MUTATION_TOOLS = {"cdr_mutator"}
    _INPUT_TOOLS = {"loop_start", "sequence_input", "sequence_db"}
    # Pass 1a: evaluated sequence comes from loop_start / sequence_input
    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        outs = node_run.outputs or {}
        tool = snap_tool.get(node_id, "")
        if tool in _INPUT_TOOLS:
            if outs.get("heavy_chain") and "vh" not in entry:
                entry["vh"] = outs["heavy_chain"]
            if outs.get("light_chain") and "vl" not in entry:
                entry["vl"] = outs["light_chain"]
    # Pass 1b: also record loop_end's next_heavy_chain for bookkeeping (not used as vh key)
    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        outs = node_run.outputs or {}
        result = outs.get("result")
        if isinstance(result, dict):
            if result.get("next_heavy_chain") and "next_vh" not in entry:
                entry["next_vh"] = result["next_heavy_chain"]
        if outs.get("next_heavy_chain") and "next_vh" not in entry:
            entry["next_vh"] = outs["next_heavy_chain"]

    # Pass 2: fallback if no input node found — any non-cdr_mutator node with heavy_chain
    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        outs = node_run.outputs or {}
        tool = snap_tool.get(node_id, "")
        if tool in _CDR_MUTATION_TOOLS:
            continue
        if outs.get("heavy_chain") and "vh" not in entry:
            entry["vh"] = outs["heavy_chain"]
        if outs.get("light_chain") and "vl" not in entry:
            entry["vl"] = outs["light_chain"]

    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        outs = node_run.outputs or {}
        tool  = snap_tool.get(node_id, "")

        # ── Embedding capture (AbMAP, ESM, AbLang, CHEAP, AA-chem, AA-onehot) ──
        # All embedding tools output standard {n, results: [{vh, vl, emb_vh, emb_vl}], metadata}.
        # Prefer the "train" node over "cand" node — cand embeds candidates, not the evaluated seq.
        if tool in _EMBEDDING_TOOLS:
            from app.tools.embedding_utils import results_to_seq_emb_dict
            emb_dict = results_to_seq_emb_dict(outs, chain="vh")
            if emb_dict:
                raw_emb = next(iter(emb_dict.values()))
                is_train = "train" in node_id.lower() and "cand" not in node_id.lower()
                if is_train or "embedding" not in entry:
                    entry["embedding"] = raw_emb

        # ── HADDOCK3 scores per rank ───────────────────────────────────
        if tool in _HADDOCK_TOOLS:
            scores = outs.get("scores")
            if isinstance(scores, dict):
                score_val = scores.get("score")
                if isinstance(score_val, (int, float)):
                    rank_key = _haddock_rank(node_id) or "rank_1"
                    entry.setdefault("haddock_scores", {})[rank_key] = float(score_val)
                    if "haddock_score" not in entry:
                        entry["haddock_score"] = float(score_val)

        # ── Generic biophysical scores (deepsp_r1, netsolp_r2, biophi_r3, …) ──
        # Any non-HADDOCK node whose ID ends with _r{N} and outputs a numeric
        # key from _GENERIC_SCORE_KEYS is captured as a DNN training rank score.
        rank_key = _haddock_rank(node_id)
        if rank_key and tool not in _HADDOCK_TOOLS:
            for sk in _GENERIC_SCORE_KEYS:
                val = outs.get(sk)
                if isinstance(val, (int, float)):
                    entry.setdefault("haddock_scores", {})[rank_key] = float(val)
                    if "haddock_score" not in entry:
                        entry["haddock_score"] = float(val)
                    break

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

    # Save fallback candidates from the ML node (2nd, 3rd, 4th ranked sequences).
    # These are used by _pick_fallback_sequence if the next iteration fails before
    # loop_end can produce a next_heavy_chain (e.g. HADDOCK returns nothing).
    _ML_TOOLS = {"rcc_mlde", "dnn_mlde", "custom_dnn"}
    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        if snap_tool.get(node_id, "") not in _ML_TOOLS:
            continue
        top_seqs = (node_run.outputs or {}).get("top_sequences")
        if isinstance(top_seqs, list) and len(top_seqs) > 1:
            # top_sequences[0] is what loop_end normally picks; save 1-3 as fallbacks
            entry["fallback_sequences"] = [s for s in top_seqs[1:4] if s]
            break  # one ML node is enough

    # Capture RL policy_state from rl_designer nodes (rolling checkpoint — not merged like
    # accumulated_dataset, just the most recent serialised Q-net + replay buffer).
    for node_id, node_run in run.nodes.items():
        if node_run.status != "succeeded":
            continue
        if snap_tool.get(node_id, "") != "rl_designer":
            continue
        ps = (node_run.outputs or {}).get("policy_state")
        if isinstance(ps, dict) and ps:
            entry["rl_policy_state"] = ps
            break  # one rl_designer node per pipeline

    return entry


def _build_accumulated_rl_state(loop_history: list[dict]) -> dict | None:
    """Return the most recent rl_policy_state from history (rolling checkpoint).

    Unlike accumulated_dataset (which merges all iterations), the RL policy
    state is a self-contained checkpoint of network weights + replay buffer —
    we only want the latest one so the agent continues from where it left off.
    """
    for entry in reversed(loop_history):
        ps = entry.get("rl_policy_state")
        if isinstance(ps, dict) and ps:
            return ps
    return None


