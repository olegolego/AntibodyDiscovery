"""ESM2 embedding adapter — runs tools/esm_embedding/run.py in its .venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


class ESMEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="esm_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("light_chain") or ""
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = str(raw).strip()

        if not sequence:
            raise ValueError("ESM2 requires a sequence (sequence, heavy_chain, or light_chain)")

        if "/" in sequence:
            sequence = sequence.split("/")[0]
            await run_ctx.alog("Multi-chain sequence — using first chain only")
        if "X" in sequence:
            sequence = sequence.replace("X", "A")
            await run_ctx.alog("Replaced non-standard residues X→A for ESM2 compatibility")

        model_size = str(inputs.get("model_size", "650M")).strip()
        pool_mode  = str(inputs.get("pool_mode",  "mean")).strip().lower()

        cache_inputs = {"sequence": sequence, "model_size": model_size, "pool_mode": pool_mode}
        cached = await self._cache.get(cache_inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored ESM2 embedding")
            return cached

        await run_ctx.alog(
            f"Running ESM2-{model_size} (pool={pool_mode}, len={len(sequence)})…"
        )
        await run_ctx.alog(
            "First run downloads weights to ~/.cache/huggingface (~700 MB for 650M)"
        )

        outputs = await run_tool_subprocess(
            tool_id="esm_embedding",
            inputs=cache_inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        dim = outputs.get("metadata", {}).get("embedding_dim", "?")
        await run_ctx.alog(f"ESM2 embedding done — dim={dim}")

        await self._cache.put(cache_inputs, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
