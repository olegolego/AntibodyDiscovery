"""Loop node adapter — runs user code with loop_history injected from the DB."""
import json
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class LoopAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        code = str(inputs.get("code", "")).strip()
        if not code:
            raise ValueError("code is required")

        # Pull loop_history and iteration from the DB via the run's loop_id
        loop_history: list[dict] = []
        loop_iteration: int = 0
        try:
            from app.db.models import LoopRunRow, RunRow
            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                row = await db.get(RunRow, run_ctx.run_id)
                if row and row.loop_id:
                    loop_iteration = row.iteration or 0
                    loop_row = await db.get(LoopRunRow, row.loop_id)
                    if loop_row and loop_row.loop_history:
                        loop_history = json.loads(loop_row.loop_history)
        except Exception:
            pass

        injected_extra = [k for k in inputs if k not in ("code", "max_iterations")]
        await run_ctx.alog(
            f"Loop iteration {loop_iteration} — running selection code "
            f"({len(injected_extra)} upstream variable(s), {len(loop_history)} history entries)…"
        )

        full_inputs = {
            **inputs,
            "loop_history": loop_history,
            "loop_iteration": loop_iteration,
        }

        outputs = await run_tool_subprocess(
            tool_id="loop",
            inputs=full_inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Loop node error:\n{outputs['error']}")
            raise RuntimeError(f"Loop node failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        next_vh = outputs.get("next_heavy_chain")
        next_vl = outputs.get("next_light_chain")
        await run_ctx.alog(
            f"Loop node done. next_heavy_chain={'set' if next_vh else 'none'}, "
            f"next_light_chain={'set' if next_vl else 'none'}"
        )
        return outputs
