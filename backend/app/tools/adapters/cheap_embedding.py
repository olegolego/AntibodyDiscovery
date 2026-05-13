"""CHEAP embedding adapter — HTTP call to tools/cheap_embedding/server.py."""
import os
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry
from app.tools.molecule_cache import MoleculeResultCache

_CHEAP_URL = os.getenv("CHEAP_EMBEDDING_URL", "http://localhost:8006")


class CHEAPEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="cheap_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("light_chain") or ""
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = str(raw).strip()

        if not sequence:
            raise ValueError("CHEAP requires a sequence (sequence, heavy_chain, or light_chain)")

        if "/" in sequence:
            sequence = sequence.split("/")[0]
            await run_ctx.alog("Multi-chain sequence — using first chain only")
        if "X" in sequence:
            sequence = sequence.replace("X", "A")
            await run_ctx.alog("Replaced non-standard residues X→A")

        shorten_factor = int(inputs.get("shorten_factor", 1))
        dim            = int(inputs.get("dim", 64))

        cache_inputs = {"sequence": sequence, "shorten_factor": shorten_factor, "dim": dim}
        cached = await self._cache.get(cache_inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored CHEAP embedding")
            return cached

        await run_ctx.alog(
            f"Running CHEAP (shorten={shorten_factor}, dim={dim}, len={len(sequence)})…"
        )
        await run_ctx.alog(
            "First call loads ESMFold trunk (~4 GB, 30–90 s on CPU)"
        )

        data = await post_with_retry(
            _CHEAP_URL,
            "/embed",
            {"sequence": sequence, "shorten_factor": shorten_factor, "dim": dim},
            tool_name="CHEAP",
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
        )

        outputs = {
            "embedding":          data["embedding"],
            "residue_embeddings": data.get("residue_embeddings"),
            "metadata":           data["metadata"],
        }

        shape = data.get("metadata", {}).get("output_shape", "?")
        await run_ctx.alog(f"CHEAP embedding done — shape {shape}")

        await self._cache.put(cache_inputs, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
