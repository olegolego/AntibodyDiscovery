"""Pipeline executor. Runs as a FastAPI BackgroundTask; persists state to DB and emits WS events."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from app.core.results_collector import collect as collect_results
from app.db.models import NodeAnalysisRow, RunRow
from app.db.session import AsyncSessionLocal
from app.models.pipeline import Pipeline
from app.models.run import NodeRun, NodeRunStatus, Run, RunStatus
from app.tools.base import RunContext
from app.tools.registry import get_large_default, tool_registry
from app.tools.registry import _SENTINEL_PREFIX
from app.tools.subprocess_runner import kill_subprocess
from app.workers.tasks import dispatch_tool

_ANALYSIS_TOOLS = {"alphafold_monomer", "esmfold", "immunebuilder", "haddock3", "equidock", "gromacs_mmpbsa"}
_cancelled_runs: set[str] = set()


def request_cancel(run_id: str) -> None:
    """Signal that a run should be cancelled. Also kills any active subprocess."""
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


async def _save_run(run: Run) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(RunRow, run.id)
        if row:
            row.status = run.status.value
            row.data = run.model_dump_json()
            row.updated_at = datetime.utcnow()
            await db.commit()


def _slim_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    """Replace large string values (PDB/FASTA) with a sentinel so WS messages stay small."""
    result = {}
    for k, v in outputs.items():
        result[k] = "__artifact__" if (isinstance(v, str) and len(v) > 512) else v
    return result


async def _emit(run: Run) -> None:
    slim = run.model_dump(mode="json")
    for nr in slim["nodes"].values():
        if nr.get("outputs"):
            nr["outputs"] = _slim_outputs(nr["outputs"])
    await manager.broadcast(run.id, {"type": "run_update", "run": slim})


async def create_run(pipeline: Pipeline) -> Run:
    run = Run(
        pipeline_id=pipeline.id,
        pipeline_snapshot=pipeline.model_dump(mode="json"),
        nodes={n.id: NodeRun(node_id=n.id) for n in pipeline.nodes},
    )
    async with AsyncSessionLocal() as db:
        db.add(RunRow(
            id=run.id,
            pipeline_id=run.pipeline_id,
            status=run.status.value,
            data=run.model_dump_json(),
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

    for node_id in order:
        # Check if cancelled before starting next node
        if run.id in _cancelled_runs:
            _cancelled_runs.discard(run.id)
            run.status = RunStatus.CANCELLED
            for nr in run.nodes.values():
                if nr.status not in (NodeRunStatus.SUCCEEDED, NodeRunStatus.FAILED):
                    nr.status = NodeRunStatus.SKIPPED
            await _save_run(run)
            await _emit(run)
            return

        node = next(n for n in pipeline.nodes if n.id == node_id)
        node_run = run.nodes[node_id]
        node_run.status = NodeRunStatus.RUNNING
        await _save_run(run)
        await _emit(run)

        spec = tool_registry.get(node.tool)
        if spec is None:
            node_run.status = NodeRunStatus.FAILED
            node_run.error = f"Unknown tool: {node.tool}"
            run.status = RunStatus.FAILED
            await _save_run(run)
            await _emit(run)
            return

        # Merge static params with resolved upstream outputs.
        # Resolve any __default_file__ sentinels to their actual file content.
        inputs: dict[str, Any] = {}
        for k, v in node.params.items():
            if isinstance(v, str) and v.startswith(_SENTINEL_PREFIX):
                content = get_large_default(node.tool, k)
                inputs[k] = content if content is not None else v
            else:
                inputs[k] = v
        # Compute nodes receive ALL outputs from every connected upstream node as
        # Python variables — don't filter to just the wired port.
        is_compute = node.tool == "compute"

        for port, upstream_ref in upstream_outputs(node_id, pipeline.edges):
            up_node, up_port = upstream_ref.split(".", 1)
            if up_node not in node_outputs:
                continue
            if is_compute:
                # Compute nodes receive every upstream output prefixed with the source node ID
                # so variables are always unique: ablang_1_embedding, ablang_2_embedding, etc.
                for k, v in node_outputs[up_node].items():
                    if v is not None:
                        inputs[f"{up_node}_{k}"] = v
            elif up_port == "out":
                inputs.update({k: v for k, v in node_outputs[up_node].items() if v is not None})
            elif up_port in node_outputs[up_node]:
                target_key = port if port != "in" else up_port
                inputs[target_key] = node_outputs[up_node][up_port]

        ctx = RunContext(run_id=run.id, node_id=node_id, node_run=node_run)
        ctx._emit_fn = lambda: _emit(run)

        try:
            outputs = await dispatch_tool(spec, inputs, ctx)
        except Exception as exc:
            node_run.status = NodeRunStatus.FAILED
            node_run.error = str(exc)
            run.status = RunStatus.FAILED
            await _save_run(run)
            await _emit(run)
            return

        node_run.outputs = outputs
        node_run.status = NodeRunStatus.SUCCEEDED
        node_outputs[node_id] = outputs
        _persist_node_outputs(run.id, node_id, node.tool, outputs)
        await collect_results(run, node_id, node.tool, inputs, outputs, node_outputs)

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
            elif "structure" in outputs or "plddt" in outputs:
                await _save_analysis(run.id, node_id, node.tool, outputs)

        await _save_run(run)
        await _emit(run)

    run.status = RunStatus.SUCCEEDED
    await _save_run(run)
    await _emit(run)


async def get_run(run_id: str) -> Run | None:
    async with AsyncSessionLocal() as db:
        row = await db.get(RunRow, run_id)
        if row is None:
            return None
        return Run.model_validate_json(row.data)
