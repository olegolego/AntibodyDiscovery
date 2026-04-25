"""Compute node adapter — executes user-supplied Python code via subprocess."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class ComputeAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        code = str(inputs.get("code", "")).strip()
        if not code:
            raise ValueError("code is required")

        injected = [k for k in inputs if k != "code"]
        await run_ctx.alog(
            f"Running Compute node ({len(injected)} injected variable(s): "
            f"{', '.join(injected) or 'none'})…"
        )

        outputs = await run_tool_subprocess(
            tool_id="compute",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,  # run in backend venv, not a separate tool venv
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Compute error:\n{outputs['error']}")
            raise RuntimeError(f"Compute node failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        await run_ctx.alog("Compute done.")
        return outputs
