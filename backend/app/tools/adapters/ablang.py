"""AbLang adapter — antibody language model embeddings via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.embedding_utils import parse_sequences, clean_seq
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


class AbLangAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="ablang", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequences = parse_sequences(inputs)
        mode = str(inputs.get("mode", "seqcoding")).lower()

        n = len(sequences)
        await run_ctx.alog(f"AbLang: {n} pair(s), mode={mode}")

        cache_key = {"sequences": sequences, "mode": mode}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        outputs = await run_tool_subprocess(
            tool_id="ablang",
            inputs={"sequences": sequences, "mode": mode},
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        await self._cache.put(cache_key, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        await run_ctx.alog(f"AbLang done — {outputs.get('n', n)} pair(s)")
        return outputs
