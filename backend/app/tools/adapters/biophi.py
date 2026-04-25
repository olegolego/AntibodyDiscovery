"""BioPhi adapter — calls tools/biophi/run.py in the 'biophi' conda env."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class BioPhiAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy = str(inputs.get("heavy_chain", "")).strip()
        light = str(inputs.get("light_chain", "") or "").strip()

        if not heavy:
            raise ValueError("heavy_chain is required")

        mode = "VH only" if not light else "VH + VL"
        await run_ctx.alog(f"Starting BioPhi Sapiens humanization ({mode})…")

        outputs = await run_tool_subprocess(
            tool_id="biophi",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        vh_mut = outputs.get("heavy_mutations", 0)
        vl_mut = outputs.get("light_mutations", 0)
        await run_ctx.alog(f"Done — {vh_mut} VH mutations, {vl_mut} VL mutations")

        return outputs
