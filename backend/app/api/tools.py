import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.core.executor import create_run, execute_run
from app.models.pipeline import NodePosition, Pipeline, PipelineEdge, PipelineNode
from app.models.run import Run
from app.models.tool_spec import ToolSpec
from app.tools.registry import tool_registry

router = APIRouter()


@router.get("/", response_model=list[ToolSpec])
async def list_tools():
    return tool_registry.all()


@router.get("/{tool_id}", response_model=ToolSpec)
async def get_tool(tool_id: str):
    spec = tool_registry.get(tool_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")
    return spec


class ToolRunRequest(BaseModel):
    params: dict = {}


@router.post("/{tool_id}/run", response_model=Run, status_code=201)
async def run_tool(tool_id: str, body: ToolRunRequest, background_tasks: BackgroundTasks):
    """Create and immediately execute a single-node pipeline for the given tool."""
    spec = tool_registry.get(tool_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found")
    node_id = f"{tool_id}_1"
    pipeline = Pipeline(
        id=str(_uuid.uuid4()),
        name=f"terminal:{tool_id}",
        schema_version="1",
        nodes=[PipelineNode(id=node_id, tool=tool_id, params=body.params, position=NodePosition(x=0, y=0))],
        edges=[],
    )
    run = await create_run(pipeline)
    background_tasks.add_task(execute_run, run.id)
    return run
