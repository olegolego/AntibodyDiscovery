"""MEGADOCK adapter — FFT-based rigid-body protein-protein docking via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess

_STRUCT_KEYS = ("structure_1", "structure_2", "structure_3", "structure_4", "structure", "pdb")


class MEGADOCKAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="megadock", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        inputs = dict(inputs)

        # Named aliases from upstream tools
        for alias, canon in (("antibody", "ligand"), ("antigen", "receptor"), ("target", "receptor")):
            if not inputs.get(canon) and inputs.get(alias):
                inputs[canon] = inputs.pop(alias)

        # Auto-detect PDB values connected via generic handles (ImmuneBuilder → ligand)
        if not inputs.get("ligand"):
            for k in _STRUCT_KEYS:
                v = inputs.get(k)
                if isinstance(v, str) and "ATOM" in v:
                    inputs["ligand"] = v
                    break
        if not inputs.get("receptor"):
            for k, v in inputs.items():
                if k not in ("ligand", "num_predictions", "rotational_sampling") and isinstance(v, str) and "ATOM" in v:
                    inputs["receptor"] = v
                    break

        if not inputs.get("ligand"):
            raise ValueError("ligand PDB is required (wire from ImmuneBuilder, ESMFold, etc.)")
        if not inputs.get("receptor"):
            raise ValueError("receptor PDB is required (wire from Target Input, AlphaFold, etc.)")

        num_pred     = max(1, min(20, int(inputs.get("num_predictions", 5))))
        rot_sampling = int(inputs.get("rotational_sampling", 3600))

        await run_ctx.alog(
            f"MEGADOCK docking | {rot_sampling} rotations | top {num_pred} predictions"
        )

        cache_key = {
            "ligand":              inputs["ligand"],
            "receptor":            inputs["receptor"],
            "num_predictions":     num_pred,
            "rotational_sampling": rot_sampling,
        }
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored MEGADOCK result")
            return cached

        outputs = await run_tool_subprocess(
            tool_id="megadock",
            inputs={
                "receptor":            inputs["receptor"],
                "ligand":              inputs["ligand"],
                "num_predictions":     num_pred,
                "rotational_sampling": rot_sampling,
            },
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        meta = outputs.get("metadata") or {}
        await run_ctx.alog(
            f"Done — best MEGADOCK score: {meta.get('best_score', '?')} "
            f"({meta.get('elapsed_seconds', '?')}s)"
        )

        await self._cache.put(cache_key, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
