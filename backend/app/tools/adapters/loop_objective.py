"""Loop objective adapter — user-defined composite objective for active learning loops."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class LoopObjectiveAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        code = str(inputs.get("code", "")).strip()
        if not code:
            raise ValueError("loop_objective: code is required")

        injected = [k for k in inputs if k != "code"]
        await run_ctx.alog(
            f"Evaluating loop objective ({len(injected)} inputs: {', '.join(injected) or 'none'})…"
        )

        outputs = await run_tool_subprocess(
            tool_id="loop_objective",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Loop objective error:\n{outputs['error']}")
            raise RuntimeError(f"loop_objective failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        obj = outputs.get("objective_score")
        await run_ctx.alog(f"Objective score: {obj}")

        # Spread result dict keys so loop_end can see {node_id}_objective_score
        result = outputs.get("result")
        if isinstance(result, dict):
            for k, v in result.items():
                if k not in outputs:
                    outputs[k] = v

        return outputs
