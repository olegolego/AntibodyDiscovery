"""Filter node adapter — removes sequences that don't meet score thresholds."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class FilterAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        score_var = str(inputs.get("score_var", "") or "")
        min_score = inputs.get("min_score")
        max_score = inputs.get("max_score")
        has_code = bool(str(inputs.get("code", "") or "").strip())

        await run_ctx.alog(
            "Filter: "
            + (f"custom code" if has_code else
               f"score_var={score_var!r}"
               + (f", min={min_score}" if min_score is not None else "")
               + (f", max={max_score}" if max_score is not None else ""))
        )

        outputs = await run_tool_subprocess(
            tool_id="filter",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Filter error:\n{outputs['error']}")
            raise RuntimeError(f"Filter node failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        count = outputs.get("count", 0)
        removed = outputs.get("removed_count", 0)
        await run_ctx.alog(f"Filter done: {count} kept, {removed} removed")
        return outputs
