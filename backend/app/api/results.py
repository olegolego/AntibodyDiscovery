"""Results database API — browse collected molecules, structures, and docking results."""
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from app.core.molecule_key import MoleculeKey
from app.db.models import (
    AbMAPEmbeddingRow,
    ToolCacheRow,
    DockingResultRow,
    DesignSequenceRow,
    EmbeddingRow,
    MoleculeRow,
    StructureRow,
)
from app.db.session import AsyncSessionLocal
from app.tools.abmap_db import abmap_cache
from app.tools.molecule_cache import (
    cache_stats_all,
    list_cache_for_key,
    list_cache_for_molecule,
)

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
            raise HTTPException(status_code=404, detail="Docking result not found")
        return {"pdb": row.best_complex_pdb}


# ── AbMAP embeddings — keyed by (VH, VL) ────────────────────────────────────

@router.get("/embeddings/abmap")
async def list_abmap_embeddings() -> list[dict[str, Any]]:
    """List all AbMAP embeddings (summary, no vectors)."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(AbMAPEmbeddingRow).order_by(AbMAPEmbeddingRow.created_at.desc())
        )).scalars().all()
    return [
        {
            "id":              r.id,
            "molecule_key":    r.molecule_key,
            "molecule_key_short": r.molecule_key[:12],
            "chain_type":      r.chain_type,
            "task":            r.task,
            "embedding_type":  r.embedding_type,
            "num_mutations":   r.num_mutations,
            "sequence_length": r.sequence_length,
            "embedding_shape": json.loads(r.embedding_shape) if r.embedding_shape else None,
            "run_id":          r.run_id,
            "created_at":      r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/embeddings/abmap/by-sequence")
async def get_abmap_by_sequence(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Look up all AbMAP embeddings for a (VH, VL) pair.

    Body: {"vh": "EVQLV...", "vl": "DIQMT..."}  (vl is optional)
    Returns summary list (no vectors). Use /embeddings/abmap/{id} to get the vector.
    """
    vh = str(body.get("vh") or body.get("heavy_chain") or "").strip()
    vl = str(body.get("vl") or body.get("light_chain") or "").strip()
    if not vh:
        raise HTTPException(status_code=422, detail="vh (heavy chain sequence) is required")
    results = await abmap_cache.list_for_molecule(vh, vl)
    return results


@router.get("/embeddings/abmap/by-key/{molecule_key}")
async def get_abmap_by_key(molecule_key: str) -> list[dict[str, Any]]:
    """Look up all AbMAP embeddings by the raw molecule_key hex string."""
    return await abmap_cache.list_for_key(molecule_key)


@router.get("/embeddings/abmap/{embedding_id}")
async def get_abmap_embedding(embedding_id: str) -> dict[str, Any]:
    """Fetch a single AbMAP embedding including the full vector."""
    result = await abmap_cache.get_embedding_by_id(embedding_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Embedding not found")
    return result


@router.get("/embeddings/abmap/stats/summary")
async def abmap_stats() -> dict[str, Any]:
    """Return aggregate stats about the AbMAP embedding cache."""
    return await abmap_cache.stats()


# ── Unified tool cache — all tools, keyed by (VH, VL) ────────────────────────

@router.get("/cache/stats")
async def tool_cache_stats() -> list[dict[str, Any]]:
    """Per-tool cache entry counts and unique molecule counts."""
    return await cache_stats_all()


@router.post("/cache/by-sequence")
async def get_cache_by_sequence(body: dict[str, Any]) -> list[dict[str, Any]]:
    """All cached results across ALL tools for a (VH, VL) pair.

    Body: {"vh": "EVQLV...", "vl": "DIQMT..."}  (vl is optional)
    """
    vh = str(body.get("vh") or body.get("heavy_chain") or "").strip()
    vl = str(body.get("vl") or body.get("light_chain") or "").strip()
    if not vh:
        raise HTTPException(status_code=422, detail="vh (heavy chain sequence) is required")
    mol_key = MoleculeKey(vh, vl)
    return await list_cache_for_molecule(vh, vl)


@router.get("/cache/by-key/{molecule_key}")
async def get_cache_by_key(molecule_key: str) -> list[dict[str, Any]]:
    """All cached results for a raw molecule_key hex string (across all tools)."""
    return await list_cache_for_key(molecule_key)
