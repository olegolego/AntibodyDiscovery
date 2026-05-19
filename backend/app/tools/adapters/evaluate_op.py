"""Evaluate node adapter — computes statistics over an upstream score dict."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class EvaluateAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        score_var = str(inputs.get("score_var", "") or "")
        has_code = bool(str(inputs.get("code", "") or "").strip())

        await run_ctx.alog(
            "Evaluate: "
            + (f"custom code" if has_code else f"score_var={score_var!r}")
        )

        outputs = await run_tool_subprocess(
            tool_id="evaluate",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Evaluate error:\n{outputs['error']}")
            raise RuntimeError(f"Evaluate node failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        summary = outputs.get("summary", {})
        if summary:
            await run_ctx.alog(
                f"Evaluate done: n={summary.get('count')}, "
                f"mean={summary.get('mean')}, "
                f"best={summary.get('best_name')!r} ({summary.get('best_score')})"
            )
        else:
            await run_ctx.alog("Evaluate done")
        return outputs
