"""BioPhi adapter — calls tools/biophi/run.py in the 'biophi' conda env."""
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess

_BIOPHI_PYTHON = Path(
    os.getenv("BIOPHI_CONDA_ENV", "/Users/oswaldkid/miniforge3/envs/biophi")
) / "bin" / "python"


class BioPhiAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="biophi", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy = str(inputs.get("heavy_chain", "")).strip()
        light = str(inputs.get("light_chain", "") or "").strip()

        if not heavy:
            raise ValueError("heavy_chain is required")

        cache_inputs = {"heavy_chain": heavy, "light_chain": light}
        cached = await self._cache.get(cache_inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored BioPhi result")
            return cached

        mode = "VH only" if not light else "VH + VL"
        await run_ctx.alog(f"Starting BioPhi Sapiens humanization ({mode})…")

        outputs = await run_tool_subprocess(
            tool_id="biophi",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_BIOPHI_PYTHON),
        )

        vh_mut = outputs.get("heavy_mutations", 0)
        vl_mut = outputs.get("light_mutations", 0)
        await run_ctx.alog(f"Done — {vh_mut} VH mutations, {vl_mut} VL mutations")

        await self._cache.put(cache_inputs, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
