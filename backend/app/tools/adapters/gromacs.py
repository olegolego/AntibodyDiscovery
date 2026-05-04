"""GROMACS MD + MM/GBSA adapter — calls tools/gromacs/run.py in its own venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess


class GROMACSAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="gromacs_mmpbsa", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        inputs = dict(inputs)

        # Accept complex_pdb from common upstream port names (MEGADOCK, HADDOCK3, EquiDock)
        if not inputs.get("complex_pdb"):
            for k, v in inputs.items():
                if k.startswith("complex_") and isinstance(v, str) and "ATOM" in v:
                    inputs["complex_pdb"] = v
                    break
        if not inputs.get("complex_pdb"):
            for k in ("best_complex", "structure", "pdb"):
                v = inputs.get(k)
                if isinstance(v, str) and "ATOM" in v:
                    inputs["complex_pdb"] = v
                    break

        if not inputs.get("complex_pdb") or "ATOM" not in str(inputs.get("complex_pdb", "")):
            raise ValueError(
                "complex_pdb is required (wire from HADDOCK3 best_complex or EquiDock best_complex)"
            )

        receptor_chains = str(inputs.get("receptor_chains", "H,L")).strip()
        ligand_chains   = str(inputs.get("ligand_chains", "B")).strip()
        production_ns   = float(inputs.get("production_ns", 10.0))
        temperature_k   = float(inputs.get("temperature_k", 300.0))
        ion_conc        = float(inputs.get("ion_concentration", 0.15))
        discard_ns      = float(inputs.get("discard_ns", 1.0))

        if not receptor_chains:
            raise ValueError("receptor_chains is required (e.g. 'H,L' or 'A')")
        if not ligand_chains:
            raise ValueError("ligand_chains is required (e.g. 'B')")
        if discard_ns >= production_ns:
            raise ValueError(
                f"discard_ns ({discard_ns}) must be less than production_ns ({production_ns})"
            )

        cache_key = {
            "complex_pdb":       inputs["complex_pdb"],
            "receptor_chains":   receptor_chains,
            "ligand_chains":     ligand_chains,
            "forcefield":        str(inputs.get("forcefield", "amber99sb-ildn")),
            "water_model":       str(inputs.get("water_model", "tip3p")),
            "temperature_k":     temperature_k,
            "ion_concentration": ion_conc,
            "production_ns":     production_ns,
            "discard_ns":        discard_ns,
            "igb":               int(inputs.get("igb", 5)),
            "mmpbsa_interval":   int(inputs.get("mmpbsa_interval", 5)),
        }

        cached = self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored GROMACS MM/GBSA result")
            return cached

        await run_ctx.alog(
            f"GROMACS MD + MM/GBSA | "
            f"receptor={receptor_chains}, ligand={ligand_chains} | "
            f"{production_ns} ns @ {temperature_k} K | "
            f"discard={discard_ns} ns"
        )
        await run_ctx.alog(
            f"Estimated wall time: {production_ns * 6:.0f}–{production_ns * 24:.0f} min "
            f"on a 32-core CPU. Logs update as each stage completes."
        )

        outputs = await run_tool_subprocess(
            tool_id="gromacs_mmpbsa",
            inputs=cache_key,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        dg = outputs.get("delta_g_bind")
        if dg is not None:
            await run_ctx.alog(f"ΔG_bind = {dg:.2f} kcal/mol")

        self._cache.put(cache_key, outputs)
        return outputs
