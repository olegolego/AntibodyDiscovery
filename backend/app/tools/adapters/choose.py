"""Choose node adapter — selects best sequence(s) from an upstream scored collection."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class ChooseAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        strategy = str(inputs.get("strategy", "top_score"))
        n = int(inputs.get("n", 1) or 1)
        score_var = str(inputs.get("score_var", "") or "")
        injected = [k for k in inputs if k not in ("strategy", "n", "score_var", "sequence_var", "code")]

        await run_ctx.alog(
            f"Choose: strategy={strategy}, n={n}"
            + (f", score_var={score_var!r}" if score_var else "")
            + f" ({len(injected)} upstream variable(s))"
        )

        outputs = await run_tool_subprocess(
            tool_id="choose",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Choose error:\n{outputs['error']}")
            raise RuntimeError(f"Choose node failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        name = outputs.get("name", "")
        score = outputs.get("score")
        ranking = outputs.get("ranking", [])
        await run_ctx.alog(
            f"Choose done: selected '{name}'"
            + (f" (score={score:.4f})" if score is not None else "")
            + (f", {len(ranking)} in full ranking" if ranking else "")
        )
        return outputs
