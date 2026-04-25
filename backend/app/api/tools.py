from fastapi import APIRouter, HTTPException

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
