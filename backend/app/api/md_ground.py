"""REST API for MD Ground: presets, saved simulations, custom force scripts,
formula/python validation, and AI code generation for custom forces.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    DockingResultRow, MDForceScriptRow, MDSavedRunRow, MDSimulationRow, MoleculeRow,
)
from app.db.session import get_db
from app.md import presets as md_presets
from app.md.custom_exec import CustomForceError, smoke_test
from app.md.pdb_import import (
    PDBImportError, build_docked_complex_spec, build_enm_spec, combine_with_target,
)
from app.md.potential_eval import FormulaError, validate_formula
from app.md.spec import SystemSpec

router = APIRouter()


# ── Presets ─────────────────────────────────────────────────────────────────

@router.get("/presets")
async def get_presets() -> dict:
    return {"presets": md_presets.list_presets()}


@router.get("/presets/{key}")
async def get_preset(key: str) -> dict:
    try:
        spec = md_presets.get_preset(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {key}")
    return {"spec": spec.model_dump()}


# ── Saved simulations ─────────────────────────────────────────────────────────

class SaveSimRequest(BaseModel):
    name: str = "Untitled simulation"
    spec: dict


@router.get("/simulations")
async def list_simulations(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(MDSimulationRow).order_by(MDSimulationRow.updated_at.desc()).limit(100)
    )).scalars().all()
    return [
        {
            "id": r.id, "name": r.name, "status": r.status,
            "created_at": r.created_at.isoformat(), "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/simulations/{sim_id}")
async def get_simulation(sim_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(MDSimulationRow, sim_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return {
        "id": row.id, "name": row.name, "status": row.status,
        "spec": json.loads(row.spec),
        "summary": json.loads(row.summary) if row.summary else None,
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    }


@router.post("/simulations", status_code=201)
async def create_simulation(body: SaveSimRequest, db: AsyncSession = Depends(get_db)) -> dict:
    # Validate the spec round-trips through the engine model.
    try:
        spec = SystemSpec.model_validate(body.spec)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid spec: {exc}")
    row = MDSimulationRow(name=body.name, spec=spec.model_dump_json(), status="draft")
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.put("/simulations/{sim_id}")
async def update_simulation(sim_id: str, body: SaveSimRequest, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(MDSimulationRow, sim_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    try:
        spec = SystemSpec.model_validate(body.spec)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid spec: {exc}")
    row.name = body.name
    row.spec = spec.model_dump_json()
    row.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": row.id}


@router.delete("/simulations/{sim_id}")
async def delete_simulation(sim_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(MDSimulationRow, sim_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": sim_id}


@router.post("/simulations/{sim_id}/cancel")
async def cancel_simulation(sim_id: str) -> dict:
    from app.md.runner import request_cancel
    request_cancel(sim_id)
    return {"status": "cancelling", "sim_id": sim_id}


# ── Saved runs (trajectory persisted in the DB, pull to replay) ───────────────

_MAX_SAVE_FRAMES = 300  # decimate trajectories to keep DB rows reasonable


class SaveRunRequest(BaseModel):
    name: str = "MD run"
    spec: dict
    particle_types: list = []
    type_index: list = []
    box_lengths: list = []
    frames: list = []           # [{step, time, positions: [..]}]
    energy_history: list = []
    summary: dict | None = None


def _decimate(items: list, cap: int) -> list:
    if len(items) <= cap:
        return items
    step = len(items) / cap
    return [items[int(i * step)] for i in range(cap)]


@router.get("/runs")
async def list_saved_runs(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(MDSavedRunRow).order_by(MDSavedRunRow.created_at.desc()).limit(200)
    )).scalars().all()
    return [
        {
            "id": r.id, "name": r.name, "n_particles": r.n_particles,
            "n_frames": r.n_frames, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/runs", status_code=201)
async def save_run(body: SaveRunRequest, db: AsyncSession = Depends(get_db)) -> dict:
    frames = _decimate(body.frames, _MAX_SAVE_FRAMES)
    n_particles = 0
    if frames and isinstance(frames[0], dict):
        n_particles = len(frames[0].get("positions", [])) // 3
    row = MDSavedRunRow(
        name=body.name or "MD run",
        spec=json.dumps(body.spec),
        particle_types=json.dumps(body.particle_types),
        type_index=json.dumps(body.type_index),
        box_lengths=json.dumps(body.box_lengths),
        frames=json.dumps(frames),
        energy_history=json.dumps(_decimate(body.energy_history, 1000)),
        summary=json.dumps(body.summary) if body.summary is not None else None,
        n_particles=n_particles,
        n_frames=len(frames),
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "n_frames": len(frames)}


@router.get("/runs/{run_id}")
async def get_saved_run(run_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Return a saved run in the shape the frontend's loadRun() expects."""
    row = await db.get(MDSavedRunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Saved run not found")
    return {
        "format": "md-ground-run",
        "version": 1,
        "name": row.name,
        "spec": json.loads(row.spec),
        "particle_types": json.loads(row.particle_types),
        "type_index": json.loads(row.type_index),
        "box_lengths": json.loads(row.box_lengths),
        "energy_history": json.loads(row.energy_history),
        "frames": json.loads(row.frames),
        "summary": json.loads(row.summary) if row.summary else None,
    }


@router.delete("/runs/{run_id}")
async def delete_saved_run(run_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(MDSavedRunRow, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Saved run not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": run_id}


# ── Custom force scripts ────────────────────────────────────────────────────

class ForceScriptRequest(BaseModel):
    name: str
    kind: str = "formula"        # formula | python
    body: str
    description: str | None = None


@router.get("/force-scripts")
async def list_force_scripts(db: AsyncSession = Depends(get_db)) -> list[dict]:
    rows = (await db.execute(
        select(MDForceScriptRow).order_by(MDForceScriptRow.updated_at.desc()).limit(200)
    )).scalars().all()
    return [
        {"id": r.id, "name": r.name, "kind": r.kind, "body": r.body, "description": r.description}
        for r in rows
    ]


@router.post("/force-scripts", status_code=201)
async def create_force_script(body: ForceScriptRequest, db: AsyncSession = Depends(get_db)) -> dict:
    row = MDForceScriptRow(name=body.name, kind=body.kind, body=body.body, description=body.description)
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.put("/force-scripts/{script_id}")
async def update_force_script(script_id: str, body: ForceScriptRequest, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(MDForceScriptRow, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Force script not found")
    row.name, row.kind, row.body, row.description = body.name, body.kind, body.body, body.description
    row.updated_at = datetime.utcnow()
    await db.commit()
    return {"id": row.id}


@router.delete("/force-scripts/{script_id}")
async def delete_force_script(script_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    row = await db.get(MDForceScriptRow, script_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Force script not found")
    await db.delete(row)
    await db.commit()
    return {"deleted": script_id}


# ── Validation ──────────────────────────────────────────────────────────────

class FormulaRequest(BaseModel):
    expression: str


@router.post("/validate-formula")
async def validate_formula_endpoint(body: FormulaRequest) -> dict:
    try:
        return validate_formula(body.expression)
    except FormulaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


class ImportPDBRequest(BaseModel):
    pdb: str
    name: str = "Imported structure"
    spring_k: float = 1.0
    temperature: float = 0.6


@router.post("/import-pdb")
async def import_pdb(body: ImportPDBRequest) -> dict:
    """Parse a PDB into an elastic-network SystemSpec (atoms = particles)."""
    try:
        spec = await asyncio.to_thread(
            build_enm_spec, body.pdb, body.name, body.spring_k, body.temperature
        )
    except PDBImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "spec": spec.model_dump(),
        "n_particles": spec.n_particles,
        "n_bonds": len(spec.bonds),
    }


class AddTargetRequest(BaseModel):
    spec: dict           # the currently-loaded SystemSpec (must have positions)
    pdb: str             # target protein PDB text
    name: str = "Target"
    gap: float = 5.0     # Å gap between the two bounding spheres
    bind_epsilon: float = 0.4


@router.post("/add-target")
async def add_target(body: AddTargetRequest) -> dict:
    """Dock a target protein next to the loaded structure (non-overlapping)."""
    try:
        base = SystemSpec.model_validate(body.spec)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid current spec: {exc}")
    try:
        combined = await asyncio.to_thread(
            combine_with_target, base, body.pdb, body.name, body.gap, body.bind_epsilon
        )
    except PDBImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "spec": combined.model_dump(),
        "n_particles": combined.n_particles,
        "n_bonds": len(combined.bonds),
    }


# ── Open a docking run (antibody + antigen, two colours) ──────────────────────

@router.get("/docking-runs")
async def list_docking_runs(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """List docking results that have a complex PDB, newest first.

    Enriched with the HADDOCK score and the antibody's identity so 100 otherwise
    identical-looking rows are actually distinguishable.
    """
    rows = (await db.execute(
        select(DockingResultRow)
        .where(DockingResultRow.best_complex_pdb.isnot(None))
        .order_by(DockingResultRow.created_at.desc())
        .limit(100)
    )).scalars().all()

    # Batch-load the linked molecules (one query, not one per row).
    mol_ids = {r.molecule_id for r in rows if r.molecule_id}
    mols: dict[str, MoleculeRow] = {}
    if mol_ids:
        mrows = (await db.execute(
            select(MoleculeRow).where(MoleculeRow.id.in_(mol_ids))
        )).scalars().all()
        mols = {m.id: m for m in mrows}

    out = []
    for r in rows:
        scores = {}
        try:
            scores = json.loads(r.scores) if r.scores else {}
        except Exception:
            scores = {}
        mol = mols.get(r.molecule_id or "")
        vh = (mol.heavy_chain if mol else None) or ""
        out.append({
            "id": r.id,
            "short_id": r.id[:8],
            "tool_id": r.tool_id,
            "antigen_label": r.antigen_label or "antigen",
            "created_at": r.created_at.isoformat(),
            "score": scores.get("score"),          # HADDOCK score (lower = better)
            "vdw": scores.get("vdw"),
            "n_models": scores.get("n_models"),
            "molecule_name": (mol.name if mol else None),
            "vh_preview": vh[:12] if vh else None,
            "vh_len": len(vh) if vh else None,
            "run_id": r.run_id,
        })
    return out


@router.post("/import-docking/{docking_id}")
async def import_docking(docking_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Open a docked complex in MD Ground, split into antibody + antigen."""
    row = await db.get(DockingResultRow, docking_id)
    if row is None or not row.best_complex_pdb:
        raise HTTPException(status_code=404, detail="Docking result or complex PDB not found")

    vh = vl = ""
    if row.molecule_id:
        mol = await db.get(MoleculeRow, row.molecule_id)
        if mol:
            vh, vl = mol.heavy_chain or "", mol.light_chain or ""

    label = row.antigen_label or "antigen"
    try:
        spec = await asyncio.to_thread(
            build_docked_complex_spec, row.best_complex_pdb, vh, vl, f"Complex — {label}",
        )
    except PDBImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    n_ab = sum(1 for t in spec.type_index if t == 0)
    return {
        "spec": spec.model_dump(),
        "n_particles": spec.n_particles,
        "n_bonds": len(spec.bonds),
        "n_antibody": n_ab,
        "n_antigen": spec.n_particles - n_ab,
    }


class PythonRequest(BaseModel):
    code: str


@router.post("/validate-python")
async def validate_python_endpoint(body: PythonRequest) -> dict:
    try:
        return await asyncio.to_thread(smoke_test, body.code)
    except CustomForceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── AI code generation (forks compute.generate_code with an MD persona) ───────

_MD_SYSTEM_PROMPT = """\
You are an expert in classical molecular dynamics and scientific Python. You \
write custom pairwise force functions for a numpy-based MD engine.

## Required interface
Define exactly one function:

    def force(pos, type_index, box, params):
        # pos: numpy float64 array, shape (N, 3) — particle positions
        # type_index: numpy int array, shape (N,) — particle species indices
        # box: object with .lengths (list of 3 floats) and .boundary (str)
        # params: dict of optional scalar parameters
        # returns: (forces, potential_energy)
        #   forces: numpy float64 array shape (N, 3)
        #   potential_energy: float
        ...

## Rules
- numpy is available as `np`. scipy and math are available.
- Vectorise over particle pairs; avoid Python loops over N where possible.
- Newton's third law: the force array must sum (approximately) to zero for \
internal forces.
- Return ONLY executable Python — no markdown fences, no prose, no comments \
outside the function.
- Do not call print(). Do not read files or network.\
"""


class CodegenRequest(BaseModel):
    prompt: str


def _extract_code(text: str) -> str:
    fenced = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return fenced.group(1).strip() if fenced else text.strip()


@router.post("/codegen")
async def codegen(body: CodegenRequest) -> dict:
    child_env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "--system-prompt", _MD_SYSTEM_PROMPT, body.prompt,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=child_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Claude CLI timed out (60s)")
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="'claude' CLI not found on PATH")

    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or stdout.decode("utf-8", errors="replace"))[:400]
        raise HTTPException(status_code=502, detail=f"Claude CLI error: {err}")

    return {"code": _extract_code(stdout.decode("utf-8", errors="replace"))}
