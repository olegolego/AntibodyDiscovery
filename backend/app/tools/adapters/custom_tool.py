"""Adapter for Workshop-published custom tools."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class CustomToolAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        await run_ctx.alog(f"Running custom tool '{self.spec.name}'…")

        outputs = await run_tool_subprocess(
            tool_id=self.spec.id,   # "custom_<uuid>" — matches tools/custom_<uuid>/run.py
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Error:\n{outputs['error']}")
            raise RuntimeError(f"Custom tool failed:\n{outputs['error']}")

        await run_ctx.alog("Done.")
        return outputs
