"""IgLM adapter — runs tools/iglm/run.py in its .venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess

_MAX_VARIANTS = 10


class IgLMAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="iglm", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Accept heavy_chain / light_chain directly, or fall back to generic sequence
        def _str(key: str, default: str = "") -> str:
            v = inputs.get(key, default)
            if isinstance(v, list):
                v = v[0] if v else ""
            s = str(v or "").strip()
            if "/" in s:
                s = s.split("/")[0]
            return s

        heavy_chain = _str("heavy_chain") or _str("sequence")
        light_chain = _str("light_chain")

        mode          = str(inputs.get("mode", "infill"))
        redesign      = str(inputs.get("redesign_chain", "vh")).lower()
        infill_region = str(inputs.get("infill_region", "cdr_h3"))
        scheme        = str(inputs.get("scheme", "imgt"))
        custom_start  = int(inputs.get("custom_start", 0))
        custom_end    = int(inputs.get("custom_end", 10))
        species       = str(inputs.get("species", "human")).lower()
        num_seqs      = min(int(inputs.get("num_sequences", 5)), _MAX_VARIANTS)
        temperature   = float(inputs.get("temperature", 1.0))
        top_p         = float(inputs.get("top_p", 1.0))
        model_name    = str(inputs.get("model_name", "IgLM"))

        runner_inputs: dict[str, Any] = {
            "mode":           mode,
            "heavy_chain":    heavy_chain,
            "light_chain":    light_chain,
            "redesign_chain": redesign,
            "infill_region":  infill_region,
            "scheme":         scheme,
            "custom_start":   custom_start,
            "custom_end":     custom_end,
            "species":        species,
            "num_sequences":  num_seqs,
            "temperature":    temperature,
            "top_p":          top_p,
            "model_name":     model_name,
        }

        cache_key = {k: runner_inputs[k] for k in sorted(runner_inputs)}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored IgLM result")
            return cached

        if mode == "log_likelihood":
            await run_ctx.alog(
                f"IgLM scoring: {len(heavy_chain)}-aa {chain_type} chain ({species})"
            )
        elif mode == "generate":
            prompt_note = f" from prompt '{heavy_chain[:20]}…'" if heavy_chain else ""
            await run_ctx.alog(
                f"IgLM generate: {num_seqs} {chain_type} sequences ({species}{prompt_note}, "
                f"T={temperature})"
            )
        else:
            region_desc = infill_region
            if redesign == "vl":
                region_desc = infill_region
            await run_ctx.alog(
                f"IgLM infill: redesign_chain={redesign}, region={region_desc}, "
                f"scheme={scheme}, n={num_seqs}, T={temperature}"
            )

        outputs = await run_tool_subprocess(
            tool_id="iglm",
            inputs=runner_inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        if mode == "log_likelihood":
            ll = outputs.get("log_likelihood")
            await run_ctx.alog(f"IgLM log_likelihood = {ll:.4f}")
        else:
            n_ready = sum(1 for i in range(1, _MAX_VARIANTS + 1) if outputs.get(f"variant_{i}"))
            await run_ctx.alog(f"IgLM done — {n_ready} variant(s) ready")

        await self._cache.put(cache_key, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
