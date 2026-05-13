"""CDR Mutator adapter — calls tools/cdr_mutator/run.py in the biophi conda env.

Uses the biophi environment because it already has abnumber + sapiens + numpy.
Point CDR_MUTATOR_PYTHON at a different interpreter to use a separate venv.
"""
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess

# Default: reuse the biophi conda env (has abnumber + sapiens)
_CDR_MUTATOR_PYTHON = Path(
    os.getenv(
        "CDR_MUTATOR_PYTHON",
        os.getenv("BIOPHI_CONDA_ENV", "/Users/oswaldkid/miniforge3/envs/biophi"),
    )
) / "bin" / "python"


class CDRMutatorAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="cdr_mutator", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy = str(inputs.get("heavy_chain", "") or "").strip()
        light = str(inputs.get("light_chain", "") or "").strip()

        if not heavy and not light:
            raise ValueError("cdr_mutator requires heavy_chain and/or light_chain")

        strategy      = str(inputs.get("strategy", "blosum62")).strip().lower()
        num_mutations = int(inputs.get("num_mutations", 3))
        num_variants  = int(inputs.get("num_variants", 10))
        scheme        = str(inputs.get("scheme", "imgt")).strip().lower()
        seed          = int(inputs.get("seed", 42))

        # CDR checkboxes (v1.1+) — pass through as-is; run.py handles defaults
        cdr_h1 = bool(inputs.get("cdr_h1", True))
        cdr_h2 = bool(inputs.get("cdr_h2", True))
        cdr_h3 = bool(inputs.get("cdr_h3", True))
        cdr_l1 = bool(inputs.get("cdr_l1", False))
        cdr_l2 = bool(inputs.get("cdr_l2", False))
        cdr_l3 = bool(inputs.get("cdr_l3", False))

        cache_key = {
            "heavy_chain":  heavy,
            "light_chain":  light,
            "strategy":     strategy,
            "cdr_h1": cdr_h1, "cdr_h2": cdr_h2, "cdr_h3": cdr_h3,
            "cdr_l1": cdr_l1, "cdr_l2": cdr_l2, "cdr_l3": cdr_l3,
            "num_mutations": num_mutations,
            "num_variants":  num_variants,
            "scheme":        scheme,
            "seed":          seed,
        }

        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored CDR Mutator result")
            return cached

        active_cdrs = [
            c for c, v in [
                ("H1", cdr_h1), ("H2", cdr_h2), ("H3", cdr_h3),
                ("L1", cdr_l1), ("L2", cdr_l2), ("L3", cdr_l3),
            ] if v
        ]
        mode_str = f"V{'H' if heavy else ''}{'L' if light else ''}"
        await run_ctx.alog(
            f"CDR Mutator: strategy={strategy}, cdrs={'+'.join(active_cdrs) or 'none'}, "
            f"mutations={num_mutations}, variants={num_variants} ({mode_str})…"
        )

        outputs = await run_tool_subprocess(
            tool_id="cdr_mutator",
            inputs=cache_key,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_CDR_MUTATOR_PYTHON),
        )

        summary = outputs.get("summary", {})
        n_h = summary.get("num_heavy_variants", 0)
        n_l = summary.get("num_light_variants", 0)
        await run_ctx.alog(f"Done — {n_h} VH variants, {n_l} VL variants generated")

        await self._cache.put(
            cache_key, outputs,
            run_id=run_ctx.run_id,
            node_id=run_ctx.node_id,
        )
        return outputs
