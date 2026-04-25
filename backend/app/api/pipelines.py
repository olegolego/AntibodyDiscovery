import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PipelineRow
from app.db.session import get_db
from app.models.pipeline import Pipeline

router = APIRouter()


@router.get("/", response_model=list[Pipeline])
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(PipelineRow).order_by(PipelineRow.updated_at.desc()))).scalars()
    return [Pipeline.model_validate_json(r.data) for r in rows]


@router.post("/", response_model=Pipeline, status_code=201)
async def create_pipeline(pipeline: Pipeline, db: AsyncSession = Depends(get_db)):
    row = PipelineRow(
        id=pipeline.id,
        name=pipeline.name,
        data=pipeline.model_dump_json(),
    )
    db.add(row)
    await db.commit()
    return pipeline


@router.get("/{pipeline_id}", response_model=Pipeline)
async def get_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(PipelineRow, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return Pipeline.model_validate_json(row.data)


@router.put("/{pipeline_id}", response_model=Pipeline)
async def update_pipeline(pipeline_id: str, pipeline: Pipeline, db: AsyncSession = Depends(get_db)):
    row = await db.get(PipelineRow, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    pipeline.id = pipeline_id
    row.name = pipeline.name
    row.data = pipeline.model_dump_json()
    row.updated_at = datetime.utcnow()
    await db.commit()
    return pipeline


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(PipelineRow, pipeline_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await db.delete(row)
    await db.commit()
