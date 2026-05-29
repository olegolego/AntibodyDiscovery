"""20-dim one-hot amino acid embedding — no GPU, no download."""
import sys
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess
from app.tools.embedding_utils import parse_sequences


class AAOneHotEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="aa_onehot_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequences = parse_sequences(inputs)
        pool_mode = str(inputs.get("pool_mode", "mean")).strip().lower()

        n = len(sequences)
        await run_ctx.alog(f"AA one-hot embedding: {n} sequence(s), pool={pool_mode}, dim=20")

        cache_key = {"sequences": sequences, "pool_mode": pool_mode}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        tool_inputs = {
            "sequences": [{"vh": s["vh"], "vl": s["vl"]} for s in sequences],
            "pool_mode": pool_mode,
        }
        outputs = await run_tool_subprocess(
            tool_id="aa_onehot_embedding",
            inputs=tool_inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=sys.executable,
        )

        if outputs.get("error"):
            raise RuntimeError(f"aa_onehot_embedding failed: {outputs['error']}")

        await self._cache.put(cache_key, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        await run_ctx.alog(f"Done — {outputs.get('n', n)} pair(s), 20-dim one-hot composition")
        return outputs
