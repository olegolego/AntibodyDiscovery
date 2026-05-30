"""Distance Selector adapter — runs tools/distance_selector/run.py via backend venv.

Selects protein residues within a given distance of a ligand in a PDB file.
From BioPipelines (Quargnali & Rivera-Fuentes 2026), Application 5.
"""
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"


class DistanceSelectorAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="distance_selector", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Accept structure from common upstream port names
        structure = (
            inputs.get("structure")
            or inputs.get("fixed_structure")
            or inputs.get("pdb")
        )
        if not structure:
            for v in inputs.values():
                if isinstance(v, str) and "ATOM" in v:
                    structure = v
                    break

        ligand   = str(inputs.get("ligand", "LIG")).strip().upper()
        distance = float(inputs.get("distance", 5.0))

        payload = {
            "structure": structure or "",
            "ligand":    ligand,
            "distance":  distance,
        }

        cached = self._cache.get(payload)
        if cached is not None:
            await run_ctx.alog("Distance Selector: cache hit")
            return cached

        await run_ctx.alog(
            f"Distance Selector: selecting residues within {distance} Å of '{ligand}'…"
        )

        outputs = await run_tool_subprocess(
            tool_id="distance_selector",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_TOOL_PYTHON),
        )

        if outputs.get("error"):
            raise RuntimeError(f"distance_selector failed: {outputs['error']}")

        n = outputs.get("selections", {}).get("n_residues", 0)
        await run_ctx.alog(f"Distance Selector: {n} pocket residue(s) selected")

        self._cache.put(payload, outputs)
        return outputs
