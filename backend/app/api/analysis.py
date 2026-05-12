"""Analysis endpoints — per-node structural analysis results."""
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.models import NodeAnalysisRow
from app.db.session import AsyncSessionLocal

router = APIRouter()


@router.get("/runs/{run_id}/nodes/{node_id}/")
async def get_node_analysis(run_id: str, node_id: str) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(NodeAnalysisRow)
                .where(NodeAnalysisRow.run_id == run_id, NodeAnalysisRow.node_id == node_id)
                .order_by(NodeAnalysisRow.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No analysis found for this run/node")

    data = json.loads(row.data)
    return {
        "run_id": run_id,
        "node_id": node_id,
        "tool_id": row.tool_id,
        "created_at": row.created_at.isoformat(),
        "structure": data.get("structure"),
        "plddt": data.get("plddt"),
        "pae": data.get("pae"),
        "water_count": data.get("water_count"),
        # megadock-specific
        "top_scores": data.get("top_scores"),
        "complex_pdbs": data.get("complex_pdbs"),
        "docking_metadata": data.get("metadata"),
        "image": data.get("image"),
        # gromacs_mmpbsa-specific
        "delta_g_bind": data.get("delta_g_bind"),
        "energy_decomposition": data.get("energy_decomposition"),
        "md_convergence": data.get("md_convergence"),
        # generic — all stored keys, used by the fallback output viewer
        "raw_outputs": data,
    }


@router.get("/runs/{run_id}/")
async def list_run_analyses(run_id: str) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(NodeAnalysisRow)
                .where(NodeAnalysisRow.run_id == run_id)
                .order_by(NodeAnalysisRow.created_at)
            )
        ).scalars().all()

    return [
        {
            "run_id": r.run_id,
            "node_id": r.node_id,
            "tool_id": r.tool_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
