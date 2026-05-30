"""Analysis endpoints — per-node structural analysis results."""
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.models import NodeAnalysisRow
from app.db.session import AsyncSessionLocal

router = APIRouter()


def _normalise_plddt(plddt: Any) -> Any:
    """Convert raw per-residue pLDDT list → stats dict expected by AnalysisPanel.

    ESMFold / Boltz2 return a list[float] in 0-1 range.
    AlphaFold already returns {mean_plddt, sequence_length, high_confidence_pct, ...}.
    Pass dicts through unchanged; convert lists to the stats shape.
    """
    if plddt is None:
        return None
    if isinstance(plddt, dict):
        return plddt  # already the right shape (AlphaFold)
    if not isinstance(plddt, list) or not plddt:
        return plddt

    # Normalise to 0-100 if values are in 0-1 range
    scale = 100.0 if max(plddt) <= 1.0 else 1.0
    scores = [v * scale for v in plddt]
    n = len(scores)
    mean_p = sum(scores) / n
    high_pct = 100.0 * sum(1 for v in scores if v >= 70) / n
    very_high_pct = 100.0 * sum(1 for v in scores if v >= 90) / n
    return {
        "mean_plddt":           round(mean_p, 1),
        "sequence_length":      n,
        "high_confidence_pct":  round(high_pct, 1),
        "very_high_confidence_pct": round(very_high_pct, 1),
        "per_residue":          scores,   # keep raw scores for potential future plot
    }


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
        "plddt": _normalise_plddt(data.get("plddt")),
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
