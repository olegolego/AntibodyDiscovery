from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.executor import create_run, execute_run, get_run, request_cancel
from app.db.models import RunRow
from app.db.session import get_db
from app.models.pipeline import Pipeline
from app.models.run import Run

router = APIRouter()


@router.post("/", response_model=Run, status_code=201)
async def submit_run(pipeline: Pipeline, background_tasks: BackgroundTasks):
    run = await create_run(pipeline)
    background_tasks.add_task(execute_run, run.id)
    return run


@router.get("/", response_model=list[Run])
async def list_runs(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(RunRow).order_by(RunRow.created_at.desc()))).scalars()
    return [Run.model_validate_json(r.data) for r in rows]


@router.get("/{run_id}", response_model=Run)
async def get_run_status(run_id: str):
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/cancel")
async def cancel_run(run_id: str):
    run = await get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in ("running", "queued"):
        raise HTTPException(status_code=400, detail=f"Run is already {run.status}")
    request_cancel(run_id)
    return {"status": "cancelling", "run_id": run_id}
