"""Developability Filter adapter — calls tools/developability_filter/run.py.

Uses the biophi conda env (has abnumber) for scheme-aware CDR detection.
"""
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

_PYTHON = Path(
    os.getenv("CDR_MUTATOR_PYTHON",
              os.getenv("BIOPHI_CONDA_ENV", "/Users/oswaldkid/miniforge3/envs/biophi"))
) / "bin" / "python"


class DevelopabilityFilterAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        payload: dict[str, Any] = {}

        # Standard batch token (preferred — wire sequences from any upstream node)
        sequences = inputs.get("sequences")
        if sequences is not None:
            payload["sequences"] = sequences
            seq_input = sequences
            if isinstance(seq_input, dict):
                n_variants = seq_input.get("n") or len(seq_input.get("variants", []))
            elif isinstance(seq_input, list):
                n_variants = len(seq_input)
            else:
                n_variants = 0
        else:
            # Legacy parallel list inputs
            vh_list = inputs.get("heavy_chain_variants")
            vl_list = inputs.get("light_chain_variants")
            if vh_list is not None:
                payload["heavy_chain_variants"] = vh_list
            if vl_list is not None:
                payload["light_chain_variants"] = vl_list
            n_variants = len(vh_list) if isinstance(vh_list, list) else 0

            # Legacy bundle-format inputs (variant_1 … variant_8)
            if not n_variants:
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

        scheme = inputs.get("scheme")
        if scheme:
            payload["scheme"] = scheme

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
