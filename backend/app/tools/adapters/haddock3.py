"""HADDOCK3 adapter — calls tools/haddock3/run.py in its own venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess


class HADDOCK3Adapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="haddock3", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        inputs = dict(inputs)
        if not inputs.get("antigen") and inputs.get("target"):
            inputs["antigen"] = inputs.pop("target")

        if not inputs.get("antibody"):
            raise ValueError("antibody PDB is required")
        if not inputs.get("antigen"):
            raise ValueError("antigen PDB is required")
        if not str(inputs.get("antigen_active_residues", "")).strip():
            raise ValueError("antigen_active_residues is required (space-separated epitope residue numbers)")

        cached = self._cache.get(inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored HADDOCK3 result")
            return cached

        vh   = str(inputs.get("vh_chain", "H") or "H").upper()
        vl   = str(inputs.get("vl_chain", "L") or "").upper()
        cdr1 = (int(inputs.get("cdr1_start", 26)), int(inputs.get("cdr1_end", 35)))
        cdr2 = (int(inputs.get("cdr2_start", 50)), int(inputs.get("cdr2_end", 58)))
        cdr3 = (int(inputs.get("cdr3_start", 95)), int(inputs.get("cdr3_end", 102)))
        sampling   = max(1, int(inputs.get("rigid_sampling", 100)))
        select_top = max(1, int(inputs.get("select_top", 50)))

        await run_ctx.alog(
            f"Mode: {'nanobody' if not vl else 'antibody'} | "
            f"CDR1 {cdr1[0]}-{cdr1[1]}, CDR2 {cdr2[0]}-{cdr2[1]}, CDR3 {cdr3[0]}-{cdr3[1]} | "
            f"sampling={sampling}, select_top={select_top}"
        )
        await run_ctx.alog("Starting HADDOCK3 via subprocess (tools/haddock3/.venv)… 15–90 min")

        outputs = await run_tool_subprocess(
            tool_id="haddock3",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        scores = outputs.get("scores") or {}
        await run_ctx.alog(
            f"Done — score={scores.get('score', '?')}, "
            f"vdw={scores.get('vdw', '?')}, "
            f"desolv={scores.get('desolv', '?')}"
        )

        self._cache.put(inputs, outputs)
        return outputs
