"""Pipeline executor. Runs as a FastAPI BackgroundTask; persists state to DB and emits WS events."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RUN_LOG_DIR = Path(os.getenv("PDP_RUN_LOG_DIR", "/tmp/pdp-runs"))
_RUN_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _persist_node_outputs(run_id: str, node_id: str, tool_id: str, outputs: dict[str, Any]) -> None:
    """Save full node outputs to disk. Never raises. Survives analysis pipeline failures."""
    try:
        path = _RUN_LOG_DIR / f"{run_id}_{node_id}_outputs.json"
        record = {
            "run_id": run_id,
            "node_id": node_id,
            "tool_id": tool_id,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "outputs": outputs,
        }
        path.write_text(json.dumps(record, indent=2))
    except Exception:
        pass

from app.core.dag import topological_sort, upstream_outputs
from app.core.events import manager
from app.core.molecule_key import MoleculeKey
from app.core.results_collector import collect as collect_results
from app.db.models import LoopRunRow, NodeAnalysisRow, RunRow
from app.db.session import AsyncSessionLocal
from app.models.pipeline import Pipeline
from app.models.run import NodeRun, NodeRunStatus, Run, RunStatus
from app.tools.base import RunContext
from app.tools.registry import get_large_default, tool_registry
from app.tools.registry import _SENTINEL_PREFIX
from app.tools.subprocess_runner import kill_subprocess
from app.workers.tasks import dispatch_tool

_ANALYSIS_TOOLS = {"alphafold_monomer", "esmfold", "immunebuilder", "haddock3", "equidock", "equifold", "megadock", "gromacs_mmpbsa", "superwater"}
_LOOP_END_TOOLS = {"loop", "loop_end"}    # trigger iteration continuation
_LOOP_START_TOOLS = {"loop_start"}         # mark the loop entry point
# Tools whose failure is non-fatal: they don't block downstream nodes and don't
# mark the run as failed. Downstream nodes simply receive no input from them.
# Used for scoring nodes (e.g. HADDOCK3 rank conformers) where some may crash
# due to bad input geometry while others succeed.
_FAULT_TOLERANT_TOOLS = {"haddock3"}

def _strip_for_generic_analysis(outputs: dict[str, Any]) -> dict[str, Any]:
    """Strip large PDB strings and float embedding arrays before saving generic analysis."""
    result = {}
    for k, v in outputs.items():
        if isinstance(v, str) and len(v) > 10_000:
            continue  # large PDB / FASTA blob
        if isinstance(v, list) and len(v) > 100 and v and isinstance(v[0], (int, float)):
            continue  # embedding vector
        result[k] = v
    return result
_cancelled_runs: set[str] = set()
_force_failed_runs: set[str] = set()


def request_cancel(run_id: str) -> None:
    """Signal that a run should be cancelled. Also kills any active subprocess."""
    _cancelled_runs.add(run_id)
    kill_subprocess(run_id)


def request_force_fail(run_id: str) -> None:
    """Signal that a run should be marked as failed (not cancelled). Also kills subprocess."""
    _force_failed_runs.add(run_id)
    _cancelled_runs.add(run_id)
    kill_subprocess(run_id)


async def _save_analysis(run_id: str, node_id: str, tool_id: str, outputs: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        row = NodeAnalysisRow(
            run_id=run_id,
            node_id=node_id,
            tool_id=tool_id,
            data=json.dumps(outputs),
        )
        db.add(row)
        await db.commit()


def _slim_run_data(run: Run) -> str:
    """Dump run to JSON, stripping large strings from pipeline_snapshot params and node
    outputs so the stored blob stays small. Replaced with sentinel strings."""
    data = run.model_dump(mode="json")
    snap = data.get("pipeline_snapshot")
    if isinstance(snap, dict):
        for node in snap.get("nodes", []):
            params = node.get("params") or {}
            node["params"] = {
                k: "__large_omitted__" if isinstance(v, str) and len(v) > 50_000 else v
                for k, v in params.items()
            }
    for nr in data.get("nodes", {}).values():
        if nr.get("outputs"):
            nr["outputs"] = _slim_outputs(nr["outputs"])
    return json.dumps(data)


async def _save_run(run: Run) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(RunRow, run.id)
        if row:
            row.status = run.status.value
            row.data = _slim_run_data(run)
            row.updated_at = datetime.utcnow()
            await db.commit()


def _slim_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    """Replace large string values (PDB/FASTA) with a sentinel so WS messages stay small."""
    result = {}
    for k, v in outputs.items():
        result[k] = "__artifact__" if (isinstance(v, str) and len(v) > 512) else v
    return result


def _sequence_input_summary(inputs: dict[str, Any]) -> str | None:
    mk = MoleculeKey.from_inputs(inputs)
    if mk is None:
        return None
    vh_len = len(mk.vh)
    vl_len = len(mk.vl)
    pieces = [f"VH len={vh_len}", f"key={mk.short()}"]
    if vl_len:
        pieces.insert(1, f"VL len={vl_len}")
    return "Inputs sequence fingerprint — " + ", ".join(pieces)


async def _emit(run: Run) -> None:
    # Persist first so WS reconnects load current logs, not stale DB state.
    await _save_run(run)
    import asyncio as _asyncio_emit
    # model_dump on a run with a large PDB (~2MB) blocks the event loop; offload to thread.
    slim = await _asyncio_emit.to_thread(run.model_dump, mode="json")
    for nr in slim["nodes"].values():
        if nr.get("outputs"):
            nr["outputs"] = _slim_outputs(nr["outputs"])
    await manager.broadcast(run.id, {"type": "run_update", "run": slim})


async def create_run(
    pipeline: Pipeline,
    loop_id: str | None = None,
    iteration: int | None = None,
) -> Run:
    # Auto-detect loop node and create a LoopRunRow on the first iteration
    if loop_id is None:
        loop_node = next((n for n in pipeline.nodes if n.tool in _LOOP_END_TOOLS), None)
        if loop_node is not None:
            import uuid as _uuid
            loop_id = str(_uuid.uuid4())
            iteration = 0
            # max_iterations lives on loop_start if present, else on the loop_end/loop node
            loop_start_node = next((n for n in pipeline.nodes if n.tool in _LOOP_START_TOOLS), None)
            max_iter = int(
                (loop_start_node.params.get("max_iterations") if loop_start_node else None)
                or loop_node.params.get("max_iterations", 5)
            )
            async with AsyncSessionLocal() as db:
                db.add(LoopRunRow(
                    id=loop_id,
                    pipeline_id=pipeline.id,
                    pipeline_snapshot=json.dumps(pipeline.model_dump(mode="json")),
                    max_iterations=max_iter,
                    current_iteration=0,
                    status="running",
                    run_ids="[]",
                    loop_history="[]",
                ))
                await db.commit()

    run = Run(
        pipeline_id=pipeline.id,
        pipeline_snapshot=pipeline.model_dump(mode="json"),
        nodes={n.id: NodeRun(node_id=n.id) for n in pipeline.nodes},
        loop_id=loop_id,
        iteration=iteration,
    )
    async with AsyncSessionLocal() as db:
        db.add(RunRow(
            id=run.id,
            pipeline_id=run.pipeline_id,
            status=run.status.value,
            data=run.model_dump_json(),
            loop_id=loop_id,
            iteration=iteration,
        ))
        await db.commit()
    return run


async def execute_run(run_id: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(RunRow, run_id)
        if row is None:
            return
        run = Run.model_validate_json(row.data)

    pipeline = Pipeline.model_validate(run.pipeline_snapshot)

    try:
        order = topological_sort(pipeline)
    except ValueError as exc:
        run.status = RunStatus.FAILED
        for node_run in run.nodes.values():
            node_run.status = NodeRunStatus.FAILED
            node_run.error = str(exc)
        await _save_run(run)
        await _emit(run)
        return

    run.status = RunStatus.RUNNING
    await _save_run(run)
    await _emit(run)

    node_outputs: dict[str, dict[str, Any]] = {}
    # Tracks nodes that failed or were skipped due to a failed parent.
    # Used to propagate "skip" to all transitive dependents.
    failed_node_ids: set[str] = set()
    # Fast lookup: node_id → tool id
    node_tool: dict[str, str] = {n.id: n.tool for n in pipeline.nodes}
    # Fast lookup: node_id → Node object
    node_map: dict[str, Any] = {n.id: n for n in pipeline.nodes}
    # Build parent map: node_id → set of direct parent node_ids
    parent_map: dict[str, set[str]] = {n.id: set() for n in pipeline.nodes}
    for e in pipeline.edges:
        child = e.target.split(".")[0]
        parent = e.source.split(".")[0]
        parent_map[child].add(parent)

    # Track which nodes have been dispatched/completed
    completed_nodes: set[str] = set()
    remaining_nodes: set[str] = set(order)

    async def _execute_single_node(node_id: str) -> None:
        """Execute one node. Updates run/node_run state in-place."""
        node = node_map[node_id]
        node_run = run.nodes[node_id]

        # Skip this node if any of its direct parents failed / were skipped.
        blocking_failed = {
            pid for pid in (parent_map[node_id] & failed_node_ids)
            if node_tool.get(pid, "") not in _FAULT_TOLERANT_TOOLS
        }
        if blocking_failed:
            node_run.status = NodeRunStatus.SKIPPED
            failed_node_ids.add(node_id)
            await _save_run(run)
            await _emit(run)
            return

        node_run.status = NodeRunStatus.RUNNING
        await _save_run(run)
        await _emit(run)

        spec = tool_registry.get(node.tool)
        if spec is None:
            node_run.status = NodeRunStatus.FAILED
            node_run.error = f"Unknown tool: {node.tool}"
            failed_node_ids.add(node_id)
            await _save_run(run)
            await _emit(run)
            return

        inputs: dict[str, Any] = {}
        for k, v in node.params.items():
            if isinstance(v, str) and v.startswith(_SENTINEL_PREFIX):
                content = get_large_default(node.tool, k)
                inputs[k] = content if content is not None else v
            else:
                inputs[k] = v
        is_compute = node.tool in ("compute", "loop", "loop_end", "choose", "filter", "rank", "evaluate")

        ctx = RunContext(run_id=run.id, node_id=node_id, node_run=node_run)
        ctx._emit_fn = lambda: _emit(run)

        try:
            for port, upstream_ref in upstream_outputs(node_id, pipeline.edges):
                up_node, up_port = upstream_ref.split(".", 1)
                if up_node not in node_outputs:
                    continue
                if is_compute:
                    for k, v in node_outputs[up_node].items():
                        if v is not None:
                            inputs[f"{up_node}_{k}"] = v
                elif up_port == "out":
                    inputs.update({k: v for k, v in node_outputs[up_node].items() if v is not None})
                elif up_port in node_outputs[up_node]:
                    val = node_outputs[up_node][up_port]
                    if port == "in" and isinstance(val, dict):
                        inputs.update({k: v for k, v in val.items() if v is not None})
                    else:
                        target_key = port if port != "in" else up_port
                        inputs[target_key] = val

            sequence_summary = _sequence_input_summary(inputs)
            if sequence_summary:
                await ctx.alog(sequence_summary)
            outputs = await dispatch_tool(spec, inputs, ctx)
        except Exception as exc:
            node_run.status = NodeRunStatus.FAILED
            node_run.error = str(exc)
            failed_node_ids.add(node_id)
            await _save_run(run)
            await _emit(run)
            return

        node_run.outputs = outputs
        node_run.status = NodeRunStatus.SUCCEEDED
        node_outputs[node_id] = outputs
        _persist_node_outputs(run.id, node_id, node.tool, outputs)
        await collect_results(run, node_id, node.tool, inputs, outputs, node_outputs)
        # Save analysis immediately so View Analysis works even on cancelled/partial runs.
        if node.tool in _ANALYSIS_TOOLS:
            try:
                if node.tool == "haddock3":
                    struct = outputs.get("best_complex")
                    scores = outputs.get("scores") or {}
                    if struct:
                        await _save_analysis(run.id, node_id, node.tool,
                                             {"structure": struct, "plddt": scores})
                elif node.tool == "equidock":
                    struct = outputs.get("best_complex")
                    meta = outputs.get("metadata") or {}
                    if struct:
                        await _save_analysis(run.id, node_id, node.tool,
                                             {"structure": struct, "plddt": meta})
                elif node.tool == "immunebuilder":
                    error_estimates = outputs.get("error_estimates") or []
                    for i in range(1, 5):
                        struct = outputs.get(f"structure_{i}")
                        if struct:
                            await _save_analysis(
                                run.id, f"{node_id}_model_{i}", node.tool,
                                {"structure": struct, "plddt": {"model_index": i,
                                                                "per_residue_rmsd": error_estimates}},
                            )
                elif node.tool == "gromacs_mmpbsa":
                    dg = outputs.get("delta_g_bind")
                    if dg is not None:
                        await _save_analysis(run.id, node_id, node.tool, {
                            "delta_g_bind": dg,
                            "energy_decomposition": outputs.get("energy_decomposition") or {},
                            "md_convergence": outputs.get("md_convergence") or {},
                        })
                elif node.tool == "superwater":
                    struct = outputs.get("hydrated_structure")
                    water_count = outputs.get("water_count") or {}
                    if struct:
                        await _save_analysis(run.id, node_id, node.tool, {
                            "structure": struct, "water_count": water_count,
                        })
                elif "structure" in outputs or "plddt" in outputs:
                    await _save_analysis(run.id, node_id, node.tool, outputs)
            except Exception:
                pass
        else:
            stripped = _strip_for_generic_analysis(outputs)
            if stripped:
                try:
                    await _save_analysis(run.id, node_id, node.tool, stripped)
                except Exception:
                    pass

    # Parallel wave-based scheduler: run all dependency-ready nodes concurrently.
    import asyncio as _asyncio
    while remaining_nodes:
        if run.id in _cancelled_runs:
            _cancelled_runs.discard(run.id)
            is_force_fail = run.id in _force_failed_runs
            _force_failed_runs.discard(run.id)
            if is_force_fail:
                run.status = RunStatus.FAILED
                for nr in run.nodes.values():
                    if nr.status not in (NodeRunStatus.SUCCEEDED, NodeRunStatus.FAILED):
                        nr.status = NodeRunStatus.FAILED
                        nr.error = "Manually marked as failed"
            else:
                run.status = RunStatus.CANCELLED
                for nr in run.nodes.values():
                    if nr.status not in (NodeRunStatus.SUCCEEDED, NodeRunStatus.FAILED):
                        nr.status = NodeRunStatus.SKIPPED
            await _save_run(run)
            await _emit(run)
            return

        # Collect nodes whose parents are all done
        ready = [
            nid for nid in remaining_nodes
            if parent_map[nid].issubset(completed_nodes)
        ]
        if not ready:
            log.error("Executor deadlock: remaining=%s, completed=%s", remaining_nodes, completed_nodes)
            break

        remaining_nodes -= set(ready)
        await _asyncio.gather(*[_execute_single_node(nid) for nid in ready])
        completed_nodes.update(ready)

    # Write final state once per wave (instead of per-node above)
    await _save_run(run)
    await _emit(run)

    # Re-read node that just ran (collect_results was called inline above)
    # The loop below mirrors the original per-node analysis persistence
    for node_id in order:
        node = node_map[node_id]
        node_run = run.nodes[node_id]
        if node_run.status != NodeRunStatus.SUCCEEDED:
            continue
        outputs = node_run.outputs or {}
        inputs: dict[str, Any] = {}  # already applied above, just for analysis hooks

        if node.tool in _ANALYSIS_TOOLS:
            if node.tool == "haddock3":
                struct = outputs.get("best_complex")
                scores = outputs.get("scores") or {}
                if struct:
                    await _save_analysis(run.id, node_id, node.tool,
                                         {"structure": struct, "plddt": scores})
            elif node.tool == "equidock":
                struct = outputs.get("best_complex")
                meta = outputs.get("metadata") or {}
                if struct:
                    await _save_analysis(run.id, node_id, node.tool,
                                         {"structure": struct, "plddt": meta})
            elif node.tool == "megadock":
                pass  # results_collector._collect_megadock_analysis saves the full analysis row
            elif node.tool == "immunebuilder":
                error_estimates = outputs.get("error_estimates") or []
                for i in range(1, 5):
                    struct = outputs.get(f"structure_{i}")
                    if struct:
                        await _save_analysis(
                            run.id, f"{node_id}_model_{i}", node.tool,
                            {
                                "structure": struct,
                                "plddt": {
                                    "model_index": i,
                                    "per_residue_rmsd": error_estimates,
                                },
                            }
                        )
            elif node.tool == "gromacs_mmpbsa":
                dg = outputs.get("delta_g_bind")
                if dg is not None:
                    await _save_analysis(run.id, node_id, node.tool, {
                        "delta_g_bind": dg,
                        "energy_decomposition": outputs.get("energy_decomposition") or {},
                        "md_convergence": outputs.get("md_convergence") or {},
                    })
            elif node.tool == "superwater":
                struct = outputs.get("hydrated_structure")
                water_count = outputs.get("water_count") or {}
                if struct:
                    await _save_analysis(run.id, node_id, node.tool, {
                        "structure": struct,
                        "water_count": water_count,
                    })
            elif "structure" in outputs or "plddt" in outputs:
                await _save_analysis(run.id, node_id, node.tool, outputs)
        else:
            # Generic analysis for all non-structure tools (AbLang, AbMAP, ProteinMPNN, compute, etc.)
            stripped = _strip_for_generic_analysis(outputs)
            if stripped:
                await _save_analysis(run.id, node_id, node.tool, stripped)

        await _save_run(run)
        await _emit(run)

    # Fault-tolerant tool failures don't count as run failures.
    hard_failures = {
        nid for nid in failed_node_ids
        if node_tool.get(nid, "") not in _FAULT_TOLERANT_TOOLS
    }
    run.status = RunStatus.FAILED if hard_failures else RunStatus.SUCCEEDED
    await _save_run(run)
    await _emit(run)

    if run.status == RunStatus.SUCCEEDED:
        await _maybe_continue_loop(run, pipeline, run_id)


async def _maybe_continue_loop(run: Run, pipeline: Pipeline, run_id: str) -> None:
    """If this run is part of a loop campaign and more iterations remain, fire the next one."""
    from app.core.loop_executor import (
        _build_history_entry, _cancelled_loops, _extract_next_sequence,
        _patch_pipeline, _save_loop,
    )

    loop_node = next((n for n in pipeline.nodes if n.tool in _LOOP_END_TOOLS), None)
    if loop_node is None:
        return

    loop_start_node = next((n for n in pipeline.nodes if n.tool in _LOOP_START_TOOLS), None)
    max_iterations = int(
        (loop_start_node.params.get("max_iterations") if loop_start_node else None)
        or loop_node.params.get("max_iterations", 5)
    )
    loop_id = run.loop_id
    if loop_id is None:
        return
    iteration = run.iteration or 0

    if loop_id in _cancelled_loops:
        _cancelled_loops.discard(loop_id)
        async with AsyncSessionLocal() as db:
            loop_row = await db.get(LoopRunRow, loop_id)
            run_ids = json.loads(loop_row.run_ids or "[]") if loop_row else []
        await _save_loop(loop_id, "cancelled", "user_cancelled", iteration, run_ids)
        return

    # Build history entry for this iteration and persist
    history_entry = await _build_history_entry(run_id, iteration, run)
    async with AsyncSessionLocal() as db:
        loop_row = await db.get(LoopRunRow, loop_id)
        if loop_row is None:
            return
        run_ids = json.loads(loop_row.run_ids or "[]")
        if run_id not in run_ids:
            run_ids.append(run_id)
        loop_history = json.loads(loop_row.loop_history or "[]")
        if history_entry:
            loop_history.append(history_entry)
        loop_row.run_ids = json.dumps(run_ids)
        loop_row.loop_history = json.dumps(loop_history)
        loop_row.current_iteration = iteration
        loop_row.updated_at = datetime.utcnow()
        await db.commit()

    if iteration + 1 >= max_iterations:
        await _save_loop(loop_id, "succeeded", "max_iterations", iteration + 1, run_ids)
        log.info("Loop %s completed %d/%d iterations", loop_id, iteration + 1, max_iterations)
        return

    # Extract next sequences and patch pipeline for next iteration.
    # Re-read the pipeline from the loop's stored snapshot so changes made
    # to the stored pipeline (e.g., improved node design) take effect on the
    # next iteration without requiring a full loop restart.
    next_vh, next_vl = _extract_next_sequence(run)
    async with AsyncSessionLocal() as db:
        _loop_row_snap = await db.get(LoopRunRow, loop_id)
        if _loop_row_snap is not None and _loop_row_snap.pipeline_snapshot:
            _snap_data = json.loads(_loop_row_snap.pipeline_snapshot)
            _fresh_pipeline = Pipeline.model_validate(_snap_data)
        else:
            _fresh_pipeline = pipeline
    next_pipeline = _patch_pipeline(_fresh_pipeline, iteration + 1, next_vh, next_vl, loop_history)
    next_run = await create_run(next_pipeline, loop_id=loop_id, iteration=iteration + 1)

    async with AsyncSessionLocal() as db:
        loop_row = await db.get(LoopRunRow, loop_id)
        if loop_row:
            all_run_ids = json.loads(loop_row.run_ids or "[]")
            if next_run.id not in all_run_ids:
                all_run_ids.append(next_run.id)
            loop_row.run_ids = json.dumps(all_run_ids)
            loop_row.current_iteration = iteration + 1
            loop_row.status = "running"
            loop_row.updated_at = datetime.utcnow()
            await db.commit()

    log.info("Loop %s — iteration %d/%d — run %s", loop_id, iteration + 2, max_iterations, next_run.id)
    await execute_run(next_run.id)


async def get_run(run_id: str) -> Run | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(RunRow, run_id)
        if row is None:
            return None
        return Run.model_validate_json(row.data)
