"""CHEAP embedding adapter — HTTP call to tools/cheap_embedding/server.py /embed_pairs."""
import os
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.embedding_utils import parse_sequences
from app.tools.http_tool import post_with_retry
from app.tools.molecule_cache import MoleculeResultCache

_CHEAP_URL = os.getenv("CHEAP_EMBEDDING_URL", "http://localhost:8006")


class CHEAPEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="cheap_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequences      = parse_sequences(inputs)
        shorten_factor = int(inputs.get("shorten_factor", 1))
        dim            = int(inputs.get("dim", 64))

        n = len(sequences)
        await run_ctx.alog(f"CHEAP: {n} pair(s), shorten={shorten_factor}, dim={dim}")
        await run_ctx.alog("First call loads ESMFold trunk (~8 GB, 30-90 s on CPU)")

        cache_key = {"sequences": sequences, "shorten_factor": shorten_factor, "dim": dim}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        data = await post_with_retry(
            _CHEAP_URL,
            "/embed_pairs",
            {"sequences": sequences, "shorten_factor": shorten_factor, "dim": dim},
            tool_name="CHEAP",
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
        )

        # Add standard sequences batch token if server didn't include it
        if "sequences" not in data and "results" in data:
            data["sequences"] = {"n": data.get("n", len(data["results"])), "variants": data["results"]}

        await self._cache.put(cache_key, data, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        await run_ctx.alog(f"CHEAP done — {data.get('n', n)} pair(s)")
        return data
