"""ESM2 embedding adapter — runs tools/esm_embedding/run.py in its .venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.embedding_utils import parse_sequences
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


class ESMEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="esm_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequences  = parse_sequences(inputs)
        model_size = str(inputs.get("model_size", "650M")).strip()
        pool_mode  = str(inputs.get("pool_mode",  "mean")).strip().lower()

        n = len(sequences)
        await run_ctx.alog(f"ESM2-{model_size}: {n} pair(s), pool={pool_mode}")
        await run_ctx.alog("First run downloads weights to ~/.cache/huggingface")

        cache_key = {"sequences": sequences, "model_size": model_size, "pool_mode": pool_mode}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        outputs = await run_tool_subprocess(
            tool_id="esm_embedding",
            inputs={"sequences": sequences, "model_size": model_size, "pool_mode": pool_mode},
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        await self._cache.put(cache_key, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        dim = (outputs.get("metadata") or {}).get("dim", "?")
        await run_ctx.alog(f"ESM2 done — {outputs.get('n', n)} pair(s), dim={dim}")
        return outputs
