"""Developability Filter adapter — calls tools/developability_filter/run.py.

Pure-stdlib runner; uses the backend Python interpreter (no extra deps needed).
Collects variant_1..8 bundles and acquisition_scores from inputs, passes them
to the subprocess, and logs the pass/fail summary.
"""
import sys
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

_PYTHON = Path(sys.executable)


class DevelopabilityFilterAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        n_variants = 0
        for i in range(1, 9):
            v = inputs.get(f"variant_{i}")
            if v:
                payload[f"variant_{i}"] = v
                n_variants += 1

        acq = inputs.get("acquisition_scores")
        if acq:
            payload["acquisition_scores"] = acq

        max_ptm = inputs.get("max_ptm_liabilities")
        if max_ptm is not None:
            payload["max_ptm_liabilities"] = int(max_ptm)

        hard_fails = inputs.get("hard_fail_checks")
        if hard_fails is not None:
            payload["hard_fail_checks"] = hard_fails

        await run_ctx.alog(f"Developability filter: assessing {n_variants} variants…")

        outputs = await run_tool_subprocess(
            tool_id="developability_filter",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_PYTHON),
        )

        n_feasible = outputs.get("n_feasible", 0)
        await run_ctx.alog(
            f"Developability filter: {n_feasible}/{n_variants} variants passed"
        )
        return outputs
