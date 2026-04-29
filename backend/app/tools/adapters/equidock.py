"""EquiDock adapter — rigid protein-protein docking via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


class EquiDockAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="equidock", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        inputs = dict(inputs)

        # Named aliases from upstream tools
        if not inputs.get("ligand") and inputs.get("antibody"):
            inputs["ligand"] = inputs.pop("antibody")
        if not inputs.get("receptor") and inputs.get("antigen"):
            inputs["receptor"] = inputs.pop("antigen")
        if not inputs.get("receptor") and inputs.get("target"):
            inputs["receptor"] = inputs.pop("target")

        # Fallback: scan all inputs for PDB content when connected via generic handles.
        # ImmuneBuilder outputs structure_1..structure_4; ESMFold/AlphaFold output 'structure'.
        # The first PDB-looking value that isn't already claimed becomes ligand.
        _PDB_KEYS = ("structure", "structure_1", "structure_2", "structure_3", "structure_4", "pdb")
        if not inputs.get("ligand"):
            for k in _PDB_KEYS:
                v = inputs.get(k)
                if isinstance(v, str) and v.strip().startswith("ATOM"):
                    inputs["ligand"] = v
                    break
        # If still nothing, pick any string that looks like a PDB (last resort)
        if not inputs.get("ligand"):
            for k, v in inputs.items():
                if k in ("receptor", "dataset", "remove_clashes", "code"):
                    continue
                if isinstance(v, str) and "ATOM" in v:
                    inputs["ligand"] = v
                    break

        if not inputs.get("ligand"):
            raise ValueError("ligand PDB is required (wire from ImmuneBuilder, ESMFold, etc.)")
        if not inputs.get("receptor"):
            raise ValueError("receptor PDB is required (wire from Target Input or upload a PDB)")

        dataset     = str(inputs.get("dataset", "dips")).lower()
        rm_clashes  = bool(inputs.get("remove_clashes", True))

        await run_ctx.alog(
            f"EquiDock rigid docking — model={dataset}, "
            f"clash_removal={'on' if rm_clashes else 'off'}"
        )

        cache_key = {
            "ligand":         inputs["ligand"],
            "receptor":       inputs["receptor"],
            "dataset":        dataset,
            "remove_clashes": rm_clashes,
        }
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored EquiDock result")
            return cached

        await run_ctx.alog("Starting EquiDock via subprocess (tools/equidock/.venv)…")

        outputs = await run_tool_subprocess(
            tool_id="equidock",
            inputs={
                "ligand":          inputs["ligand"],
                "receptor":        inputs["receptor"],
                "dataset":         dataset,
                "remove_clashes":  rm_clashes,
            },
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        meta = outputs.get("metadata") or {}
        await run_ctx.alog(
            f"Done — {meta.get('ligand_residues', '?')} ligand residues docked, "
            f"|t| = {round(float(sum(x**2 for x in meta.get('translation', [0,0,0]))**0.5), 2)} Å"
        )

        await self._cache.put(cache_key, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
