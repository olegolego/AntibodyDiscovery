"""Analysis endpoints — per-node structural analysis results."""
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.db.models import NodeAnalysisRow
from app.db.session import AsyncSessionLocal

router = APIRouter()


@router.get("/runs/{run_id}/nodes/{node_id}")
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
    }


@router.get("/runs/{run_id}")
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
