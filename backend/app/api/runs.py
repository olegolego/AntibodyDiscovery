import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel as _Base
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sql_delete

from app.core.executor import create_run, execute_run, get_run, request_cancel, request_force_fail
from app.db.models import (
    DockingResultRow, DesignSequenceRow, EmbeddingRow,
    NodeAnalysisRow, RunRow, StructureRow,
)
from app.db.session import get_db
from app.models.pipeline import Pipeline
from app.models.run import Run

router = APIRouter()

# ── Report models ─────────────────────────────────────────────────────────────

class _RV(_Base):
    label: str
    value: float | int | str | None = None
    unit: str | None = None

class _Metrics(_Base):
    primary: _RV | None = None
    secondary: list[_RV] = []
    confidence: str = "neutral"  # high | medium | low | neutral | error

class _NodeReport(_Base):
    node_id: str
    tool_id: str
    tool_name: str
    status: str
    error_excerpt: str | None = None
    has_analysis: bool = False
    metrics: _Metrics | None = None

class _RunReport(_Base):
    run_id: str
    status: str
    created_at: str | None = None
    pipeline_name: str
    nodes: list[_NodeReport]

# ── Report helpers ────────────────────────────────────────────────────────────

_TOOL_NAMES: dict[str, str] = {
    "immunebuilder": "ImmuneBuilder",
    "esmfold": "ESMFold",
    "alphafold_monomer": "AlphaFold",
    "haddock3": "HADDOCK3",
    "megadock": "MEGADOCK",
    "equidock": "EquiDock",
    "gromacs_mmpbsa": "GROMACS MM/GBSA",
    "proteinmpnn": "ProteinMPNN",
    "rfdiffusion": "RFdiffusion",
    "superwater": "SuperWater",
    "biophi": "BioPhi",
    "sequence_input": "Sequence Input",
    "sequence_db": "Sequence Library",
    "target_input": "Target Input",
    "ablang": "AbLang",
    "abmap": "AbMAP",
}

def _has_analysis(outputs: dict[str, Any]) -> bool:
    return bool(outputs)

def _rv(label: str, value: Any, unit: str | None = None) -> _RV:
    return _RV(label=label, value=value, unit=unit)

def _extract_metrics(tool_id: str, outputs: dict[str, Any]) -> _Metrics:
    M = _Metrics

    if tool_id == "immunebuilder":
        errs: list = outputs.get("error_estimates") or []
        models = sum(1 for i in range(1, 5) if outputs.get(f"structure_{i}") is not None)
        if errs:
            mean_rmsd = round(sum(errs) / len(errs), 3)
            conf = "high" if mean_rmsd < 0.3 else ("medium" if mean_rmsd < 0.8 else "low")
            return M(
                primary=_rv("Mean RMSD", mean_rmsd, "Å"),
                secondary=[_rv("Residues", len(errs)), _rv("Models", models)],
                confidence=conf,
            )
        return M(secondary=[_rv("Models", models)], confidence="neutral")

    if tool_id == "esmfold":
        plddt = outputs.get("plddt")
        if isinstance(plddt, list) and plddt:
            mean_p = round(sum(plddt) / len(plddt), 1)
            n = len(plddt)
            high_pct = round(100 * sum(1 for v in plddt if v >= 70) / n, 1)
            conf = "high" if mean_p >= 80 else ("medium" if mean_p >= 60 else "low")
            return M(
                primary=_rv("Mean pLDDT", mean_p),
                secondary=[_rv("Residues", n), _rv("High conf", high_pct, "%")],
                confidence=conf,
            )
        return M(confidence="neutral")

    if tool_id == "alphafold_monomer":
        plddt = outputs.get("plddt")
        if isinstance(plddt, dict):
            mean_p = plddt.get("mean_plddt")
            conf = "high" if (mean_p or 0) >= 80 else ("medium" if (mean_p or 0) >= 60 else "low")
            return M(
                primary=_rv("Mean pLDDT", mean_p),
                secondary=[
                    _rv("Residues", plddt.get("sequence_length")),
                    _rv("High conf", plddt.get("high_confidence_pct"), "%"),
                    _rv("Very high", plddt.get("very_high_confidence_pct"), "%"),
                ],
                confidence=conf,
            )
        return M(confidence="neutral")

    if tool_id == "haddock3":
        scores = outputs.get("scores") or {}
        score = scores.get("score")
        if score is not None:
            conf = "high" if score <= -50 else ("medium" if score <= -20 else "low")
            return M(
                primary=_rv("HADDOCK score", round(score, 2)),
                secondary=[
                    _rv("vdW", round(scores["vdw"], 2) if scores.get("vdw") is not None else None, "kcal/mol"),
                    _rv("Desolvation", round(scores["desolv"], 2) if scores.get("desolv") is not None else None, "kcal/mol"),
                    _rv("BSA", round(scores["bsa"], 0) if scores.get("bsa") is not None else None, "Å²"),
                    _rv("Models", scores.get("n_models")),
                ],
                confidence=conf,
            )
        return M(confidence="neutral")

    if tool_id == "megadock":
        meta = outputs.get("metadata") or {}
        top = outputs.get("top_scores") or []
        best = meta.get("best_score") or (top[0]["score"] if top else None)
        elapsed = meta.get("elapsed_seconds")
        return M(
            primary=_rv("Best score", round(best, 2) if best is not None else None),
            secondary=[
                _rv("Poses", len(top)),
                _rv("Time", round(elapsed, 1) if elapsed is not None else None, "s"),
            ],
            confidence="neutral",
        )

    if tool_id == "gromacs_mmpbsa":
        dg = outputs.get("delta_g_bind")
        if dg is not None:
            conf = "high" if dg <= -10 else ("medium" if dg <= -5 else "low")
            decomp = outputs.get("energy_decomposition") or {}
            secondary = [
                _rv(k, round(v, 2), "kcal/mol")
                for k, v in list(decomp.items())[:3]
                if isinstance(v, (int, float))
            ]
            return M(primary=_rv("ΔG bind", round(dg, 2), "kcal/mol"), secondary=secondary, confidence=conf)
        return M(confidence="neutral")

    if tool_id == "proteinmpnn":
        seqs = outputs.get("sequence") or []
        return M(primary=_rv("Sequences designed", len(seqs) if isinstance(seqs, list) else 0), confidence="neutral")

    if tool_id == "rfdiffusion":
        meta = outputs.get("metadata") or {}
        return M(
            primary=_rv("Designs", meta.get("num_designs")),
            secondary=[_rv("Residues", meta.get("num_residues")), _rv("Steps", meta.get("diffusion_steps"))],
            confidence="neutral",
        )

    if tool_id == "superwater":
        wc = outputs.get("water_count") or {}
        return M(primary=_rv("Waters placed", wc.get("waters_placed")), confidence="neutral")

    if tool_id == "biophi":
        vh = outputs.get("heavy_mutations") or 0
        vl = outputs.get("light_mutations") or 0
        total = vh + vl
        conf = "high" if total <= 5 else ("medium" if total <= 15 else "low")
        return M(
            primary=_rv("Total mutations", total),
            secondary=[_rv("VH mutations", vh), _rv("VL mutations", vl)],
            confidence=conf,
        )

    if tool_id in ("sequence_input", "sequence_db"):
        heavy = outputs.get("heavy_chain") or ""
        light = outputs.get("light_chain") or ""
        return M(
            primary=_rv("VH length", len(heavy) if heavy else None, "AA"),
            secondary=[_rv("VL length", len(light), "AA")] if light else [],
            confidence="neutral",
        )

    return M(confidence="neutral")


@router.post("/", response_model=Run, status_code=201)
async def submit_run(pipeline: Pipeline, background_tasks: BackgroundTasks):
    run = await create_run(pipeline)
    background_tasks.add_task(execute_run, run.id)
    return run


@router.get("/")
async def list_runs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(RunRow).order_by(RunRow.created_at.desc()).limit(100))).scalars().all()
    result = []
    for r in rows:
        # Use raw JSON parse instead of full Pydantic validation — avoids deserializing
        # large logs/outputs blobs that the list view doesn't need.
        raw: dict = json.loads(r.data)
        if not raw.get("created_at"):
            raw["created_at"] = r.created_at.isoformat()
        # Drop per-node outputs and logs in-place (can be megabytes for long runs)
        for node in raw.get("nodes", {}).values():
            node.pop("outputs", None)
            node.pop("logs", None)
        # Drop pipeline snapshot edges and node params
        snap = raw.get("pipeline_snapshot") or {}
        snap.pop("edges", None)
        for n in snap.get("nodes", []):
            n.pop("params", None)
        result.append(raw)
    # Return as JSONResponse to skip FastAPI's response-side Pydantic serialization too
    return JSONResponse(result)


@router.get("/{run_id}/", response_model=Run)
async def get_run_status(run_id: str):
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/cancel/")
async def cancel_run(run_id: str):
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("running", "queued"):
        raise HTTPException(status_code=400, detail=f"Run is already {run.status}")
    request_cancel(run_id)
    return {"status": "cancelling", "run_id": run_id}


@router.delete("/{run_id}/")
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(RunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row.status in ("running", "queued"):
        raise HTTPException(status_code=400, detail="Cannot delete a running run — cancel it first")
    # Cascade-delete all result rows linked to this run so no orphaned records remain
    for model in (NodeAnalysisRow, StructureRow, DockingResultRow, DesignSequenceRow, EmbeddingRow):
        await db.execute(sql_delete(model).where(model.run_id == run_id))
    await db.delete(row)
    await db.commit()
    # Clear in-memory molecule cache so stale entries don't prevent re-creation
    from app.core.results_collector import _molecule_cache
    _molecule_cache.clear()
    return {"deleted": run_id}


@router.post("/{run_id}/force-fail/")
async def force_fail_run(run_id: str, db: AsyncSession = Depends(get_db)):
    """Stop a running/queued run and mark it as failed."""
    row = await db.get(RunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if row.status not in ("running", "queued"):
        raise HTTPException(status_code=400, detail=f"Run is already {row.status}")
    # Signal executor to stop and mark as failed (handles active background tasks).
    request_force_fail(run_id)
    # Also update DB directly as a fallback for runs with no active executor.
    try:
        data = json.loads(row.data)
        data["status"] = "failed"
        for node in data.get("nodes", {}).values():
            if node.get("status") in ("running", "queued", "pending"):
                node["status"] = "failed"
                node["error"] = "Manually marked as failed"
        row.status = "failed"
        row.data = json.dumps(data)
        row.updated_at = datetime.utcnow()
    except Exception:
        row.status = "failed"
        row.updated_at = datetime.utcnow()
    await db.commit()
    return {"status": "failed", "run_id": run_id}


@router.post("/{run_id}/rerun/", response_model=Run, status_code=201)
async def rerun_run(run_id: str, background_tasks: BackgroundTasks):
    existing = await get_run(run_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Run not found")
    pipeline = Pipeline.model_validate(existing.pipeline_snapshot)
    run = await create_run(pipeline)
    background_tasks.add_task(execute_run, run.id)
    return run


@router.get("/{run_id}/report/", response_model=_RunReport)
async def get_run_report(run_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(RunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    run = Run.model_validate_json(row.data)
    snapshot = run.pipeline_snapshot
    pipeline_name = str(snapshot.get("name", "Untitled pipeline"))

    tool_map: dict[str, str] = {
        n["id"]: n["tool"] for n in snapshot.get("nodes", [])
    }
    node_order: list[str] = [n["id"] for n in snapshot.get("nodes", [])]

    nodes: list[_NodeReport] = []
    for node_id in node_order:
        node_run = run.nodes.get(node_id)
        if node_run is None:
            continue
        tool_id = tool_map.get(node_id, "unknown")
        outputs = node_run.outputs or {}
        status_str = node_run.status.value if hasattr(node_run.status, "value") else str(node_run.status)

        metrics: _Metrics | None = None
        if status_str == "succeeded":
            metrics = _extract_metrics(tool_id, outputs)
        elif status_str == "failed":
            metrics = _Metrics(confidence="error")

        nodes.append(_NodeReport(
            node_id=node_id,
            tool_id=tool_id,
            tool_name=_TOOL_NAMES.get(tool_id, tool_id),
            status=status_str,
            error_excerpt=(node_run.error or "")[:200] if node_run.error else None,
            has_analysis=_has_analysis(outputs),
            metrics=metrics,
        ))

    run_status = run.status.value if hasattr(run.status, "value") else str(run.status)
    return _RunReport(
        run_id=run_id,
        status=run_status,
        created_at=run.created_at or row.created_at.isoformat(),
        pipeline_name=pipeline_name,
        nodes=nodes,
    )
