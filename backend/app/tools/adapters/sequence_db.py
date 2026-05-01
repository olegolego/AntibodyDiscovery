"""Adapter for sequence_db — passes the embedded VH/VL sequences downstream.

Sequences are written into node params at picker-selection time, so this
adapter simply echoes them. Identical in behaviour to sequence_input.
"""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext


class SequenceDbAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        vh = str(inputs.get("heavy_chain") or "").strip()
        vl = str(inputs.get("light_chain") or "").strip()
        if not vh:
            raise ValueError("sequence_db: heavy_chain is empty — select a sequence from the library first")
        await run_ctx.alog(f"sequence_db: VH {len(vh)} AA" + (f", VL {len(vl)} AA" if vl else " (nanobody)"))
        return {"heavy_chain": vh, "light_chain": vl}
