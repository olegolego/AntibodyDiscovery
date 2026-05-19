"""Liability Scanner adapter — pure Python, no external deps.
Runs tools/liability_scanner/run.py with the backend's own interpreter.
"""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


class LiabilityScannerAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy = str(inputs.get("heavy_chain", "") or "").strip()
        light = str(inputs.get("light_chain", "") or "").strip()

        if not heavy:
            raise ValueError("liability_scanner requires heavy_chain")

        chains = "VH+VL" if light else "VH only"
        await run_ctx.alog(f"Scanning {chains} for liability motifs…")

        outputs = await run_tool_subprocess(
            tool_id="liability_scanner",
            inputs={"heavy_chain": heavy, "light_chain": light},
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        n = outputs.get("n_liabilities", 0)
        await run_ctx.alog(f"Done — {n} liability motif{'s' if n != 1 else ''} found")
        return outputs
