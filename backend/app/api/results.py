"""Results database API — browse collected molecules, structures, and docking results."""
import json
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select, func

from app.db.models import (
    DockingResultRow,
    DesignSequenceRow,
    EmbeddingRow,
    MoleculeRow,
    StructureRow,
)
from app.db.session import AsyncSessionLocal

router = APIRouter()


def _scores(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


@router.get("/molecules")
async def list_molecules() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(MoleculeRow).order_by(MoleculeRow.created_at.desc())
        )).scalars().all()

        result = []
        for m in rows:
            # Count linked records
            structs = (await db.execute(
                select(func.count()).where(StructureRow.molecule_id == m.id)
            )).scalar() or 0
            docks = (await db.execute(
                select(func.count()).where(DockingResultRow.molecule_id == m.id)
            )).scalar() or 0
            designs = (await db.execute(
                select(func.count()).where(DesignSequenceRow.molecule_id == m.id)
            )).scalar() or 0

            result.append({
                "id": m.id,
                "name": m.name,
                "heavy_chain": m.heavy_chain,
                "light_chain": m.light_chain,
                "run_id": m.run_id,
                "pipeline_id": m.pipeline_id,
                "created_at": m.created_at.isoformat(),
                "counts": {
                    "structures": structs,
                    "docking_results": docks,
                    "design_sequences": designs,
                },
            })
        return result


@router.get("/molecules/{molecule_id}")
async def get_molecule(molecule_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        mol = await db.get(MoleculeRow, molecule_id)
        if mol is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Molecule not found")

        structs = (await db.execute(
            select(StructureRow).where(StructureRow.molecule_id == molecule_id)
            .order_by(StructureRow.created_at.asc())
        )).scalars().all()

        docks = (await db.execute(
            select(DockingResultRow).where(DockingResultRow.molecule_id == molecule_id)
            .order_by(DockingResultRow.created_at.asc())
        )).scalars().all()

        designs = (await db.execute(
            select(DesignSequenceRow).where(DesignSequenceRow.molecule_id == molecule_id)
            .order_by(DesignSequenceRow.created_at.asc())
        )).scalars().all()

        embeddings = (await db.execute(
            select(EmbeddingRow).where(EmbeddingRow.molecule_id == molecule_id)
        )).scalars().all()

        return {
            "id": mol.id,
            "name": mol.name,
            "heavy_chain": mol.heavy_chain,
            "light_chain": mol.light_chain,
            "run_id": mol.run_id,
            "pipeline_id": mol.pipeline_id,
            "created_at": mol.created_at.isoformat(),
            "structures": [
                {
                    "id": s.id,
                    "tool_id": s.tool_id,
                    "model_rank": s.model_rank,
                    "has_pdb": bool(s.pdb_data),
                    "confidence": _scores(s.confidence),
                    "run_id": s.run_id,
                    "node_id": s.node_id,
                    "created_at": s.created_at.isoformat(),
                }
                for s in structs
            ],
            "docking_results": [
                {
                    "id": d.id,
                    "antigen_label": d.antigen_label,
                    "scores": _scores(d.scores),
                    "has_complex": bool(d.best_complex_pdb),
                    "run_id": d.run_id,
                    "node_id": d.node_id,
                    "created_at": d.created_at.isoformat(),
                }
                for d in docks
            ],
            "design_sequences": [
                {
                    "id": ds.id,
                    "tool_id": ds.tool_id,
                    "sequences": json.loads(ds.sequences or "[]"),
                    "scores": _scores(ds.scores),
                    "has_backbone": bool(ds.backbone_pdb),
                    "run_id": ds.run_id,
                    "created_at": ds.created_at.isoformat(),
                }
                for ds in designs
            ],
            "embeddings": [
                {
                    "id": e.id,
                    "tool_id": e.tool_id,
                    "run_id": e.run_id,
                    "created_at": e.created_at.isoformat(),
                }
                for e in embeddings
            ],
        }


@router.get("/structures/{structure_id}/pdb")
async def get_structure_pdb(structure_id: str) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        row = await db.get(StructureRow, structure_id)
        if row is None or not row.pdb_data:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Structure not found")
        return {"pdb": row.pdb_data}


@router.get("/docking/{docking_id}/pdb")
async def get_docking_pdb(docking_id: str) -> dict[str, str]:
    async with AsyncSessionLocal() as db:
        row = await db.get(DockingResultRow, docking_id)
        if row is None or not row.best_complex_pdb:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Docking result not found")
        return {"pdb": row.best_complex_pdb}
