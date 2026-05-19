"""Rank node adapter — sorts sequences by score and annotates with rank."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class RankAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        score_var = str(inputs.get("score_var", "") or "")
        order = str(inputs.get("order", "descending") or "descending")
        top_k = int(inputs.get("top_k", 0) or 0)
        has_code = bool(str(inputs.get("code", "") or "").strip())

        await run_ctx.alog(
            "Rank: "
            + (f"custom code" if has_code else
               f"score_var={score_var!r}, order={order}"
               + (f", top_k={top_k}" if top_k > 0 else ""))
        )

        outputs = await run_tool_subprocess(
            tool_id="rank",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Rank error:\n{outputs['error']}")
            raise RuntimeError(f"Rank node failed:\n{outputs['error']}")

        if outputs.get("stdout"):
            for line in outputs["stdout"].splitlines():
                await run_ctx.alog(f"[stdout] {line}")

        ranking = outputs.get("ranking", [])
        await run_ctx.alog(f"Rank done: {len(ranking)} sequences ranked")
        return outputs
