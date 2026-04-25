"""AbLang adapter — antibody language model embeddings via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess


class AbLangAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="ablang", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequence = str(inputs.get("sequence", "")).strip()
        chain_type = str(inputs.get("chain_type", "H")).upper()
        mode = str(inputs.get("mode", "seqcoding")).lower()

        if not sequence:
            raise ValueError("sequence is required")

        cache_inputs = {"sequence": sequence, "chain_type": chain_type, "mode": mode}
        cached = self._cache.get(cache_inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        await run_ctx.alog(
            f"Starting AbLang (chain={chain_type}, mode={mode}, len={len(sequence)})…"
        )

        outputs = await run_tool_subprocess(
            tool_id="ablang",
            inputs={"sequence": sequence, "chain_type": chain_type, "mode": mode},
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        shape = outputs.get("metadata", {}).get("output_shape", "?")
        await run_ctx.alog(f"AbLang complete — output shape {shape}")

        self._cache.put(cache_inputs, outputs)
        return outputs
