"""Loop Start adapter — passes sequences through and marks the beginning of the loop region."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext


class LoopStartAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        vh = str(inputs.get("heavy_chain") or "").strip()
        vl = str(inputs.get("light_chain") or "").strip()
        max_iter = int(inputs.get("max_iterations", 5))

        # Pull current iteration from DB for the log message
        iteration = 0
        try:
            from app.db.models import RunRow
            from app.db.session import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                row = await db.get(RunRow, run_ctx.run_id)
                if row:
                    iteration = row.iteration or 0
        except Exception:
            pass

        await run_ctx.alog(
            f"Loop iteration {iteration + 1}/{max_iter} — "
            f"VH {len(vh)} AA{f', VL {len(vl)} AA' if vl else ''}"
        )
        return {"heavy_chain": vh, "light_chain": vl}
