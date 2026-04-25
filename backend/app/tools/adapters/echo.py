"""Mock adapter that echoes inputs back as outputs. Useful for testing pipelines end-to-end."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext


class EchoAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        run_ctx.log(f"echo: received inputs: {list(inputs.keys())}")
        return inputs
