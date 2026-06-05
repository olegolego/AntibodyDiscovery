"""ProGen2 adapter — runs tools/progen2/run.py in its .venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess

_MAX_VARIANTS = 10


class ProGen2Adapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="progen2", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        def _str(key: str, default: str = "") -> str:
            v = inputs.get(key, default)
            if isinstance(v, list):
                v = v[0] if v else ""
            s = str(v or "").strip()
            if "/" in s:
                s = s.split("/")[0]
            return s

        # Prefer heavy_chain (upstream edge) over sequence (node param) so that
        # connecting sequence_input.out → progen2.in actually drives generation.
        sequence    = _str("heavy_chain") or _str("sequence")
        light_chain = _str("light_chain")
        mode        = str(inputs.get("mode", "generate"))
        num_seqs    = min(int(inputs.get("num_sequences", 5)), _MAX_VARIANTS)
        max_length  = int(inputs.get("max_length", 150))
        temperature = float(inputs.get("temperature", 1.0))
        top_p       = float(inputs.get("top_p", 0.9))
        top_k       = int(inputs.get("top_k", 0))
        model_name  = str(inputs.get("model_name", "progen2-oas"))

        runner_inputs: dict[str, Any] = {
            "mode":          mode,
            "sequence":      sequence,
            "light_chain":   light_chain,
            "num_sequences": num_seqs,
            "max_length":    max_length,
            "temperature":   temperature,
            "top_p":         top_p,
            "top_k":         top_k,
            "model_name":    model_name,
        }

        cache_key = {k: runner_inputs[k] for k in sorted(runner_inputs)}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored ProGen2 result")
            return cached

        if mode == "log_likelihood":
            await run_ctx.alog(
                f"ProGen2 scoring: {len(sequence)}-aa sequence ({model_name})"
            )
        else:
            prompt_note = f" from {len(sequence)}-aa prompt" if sequence else " de novo"
            await run_ctx.alog(
                f"ProGen2 generate: {num_seqs} sequences{prompt_note} "
                f"({model_name}, T={temperature})"
            )

        outputs = await run_tool_subprocess(
            tool_id="progen2",
            inputs=runner_inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        if mode == "log_likelihood":
            ll = outputs.get("log_likelihood")
            await run_ctx.alog(f"ProGen2 log_likelihood = {ll:.4f}")
        else:
            n_ready = sum(1 for i in range(1, _MAX_VARIANTS + 1) if outputs.get(f"variant_{i}"))
            await run_ctx.alog(f"ProGen2 done — {n_ready} variant(s) ready")

        await self._cache.put(cache_key, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
