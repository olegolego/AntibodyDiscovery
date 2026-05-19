"""DeepSP adapter — uses the abmap conda env (has ANARCI + numpy).
Runs tools/deepsp/run.py to compute SAP, surface charge, and surface hydrophobicity.
"""
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

_DEEPSP_PYTHON = Path(
    os.getenv("ABMAP_CONDA_ENV", "/Users/oswaldkid/miniforge3/envs/abmap")
) / "bin" / "python"


class DeepSPAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy = str(inputs.get("heavy_chain", "") or "").strip()
        light = str(inputs.get("light_chain", "") or "").strip()

        if not heavy:
            raise ValueError("deepsp requires heavy_chain")

        chains = "VH+VL" if light else "VH only"
        await run_ctx.alog(f"Running DeepSP on {chains} (ANARCI Chothia numbering)…")

        outputs = await run_tool_subprocess(
            tool_id="deepsp",
            inputs={"heavy_chain": heavy, "light_chain": light},
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_DEEPSP_PYTHON),
        )

        sap = outputs.get("sap_score", "?")
        charge = outputs.get("surface_charge", "?")
        await run_ctx.alog(f"Done — SAP={sap}, surface charge={charge}")
        return outputs
