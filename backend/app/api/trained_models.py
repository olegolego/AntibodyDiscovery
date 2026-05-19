"""REST endpoints for the trained model registry."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TrainedModelRow
from app.db.session import get_db

router = APIRouter()


def _row_to_summary(row: TrainedModelRow) -> dict[str, Any]:
    metrics = {}
    if row.metrics:
        try:
            metrics = json.loads(row.metrics)
        except Exception:
            pass
    return {
        "id": row.id,
        "name": row.name,
        "run_id": row.run_id,
        "node_id": row.node_id,
        "embedding_model": row.embedding_model,
        "task": row.task,
        "num_sequences": row.num_sequences,
        "metrics": metrics,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/")
async def list_models(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(TrainedModelRow).order_by(TrainedModelRow.created_at.desc())
        )
    ).scalars().all()
    return [_row_to_summary(r) for r in rows]


@router.get("/{model_id}")
async def get_model(model_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    row = await db.get(TrainedModelRow, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")

    arch_spec = None
    if row.architecture_spec:
        try:
            arch_spec = json.loads(row.architecture_spec)
        except Exception:
            arch_spec = row.architecture_spec

    return {
        **_row_to_summary(row),
        "model_artifact": {
            "architecture_spec": arch_spec,
            "embedding_model": row.embedding_model,
            "task": row.task,
            "weights_b64": row.weights_b64,
        },
    }


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: str, db: AsyncSession = Depends(get_db)) -> None:
    row = await db.get(TrainedModelRow, model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Model not found")
    await db.delete(row)
    await db.commit()
