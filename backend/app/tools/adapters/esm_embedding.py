"""ESM2 embedding adapter — runs tools/esm_embedding/run.py in its .venv."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.fasta_utils import is_multi_fasta, parse_fasta
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


def _clean_seq(seq: str) -> str:
    if "/" in seq:
        seq = seq.split("/")[0]
    if "X" in seq:
        seq = seq.replace("X", "A")
    return seq.strip()


class ESMEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="esm_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # When this node is wired from Sequence Input, the tool may still carry a
        # default/demo `sequence` param from its YAML spec. Prefer connected chain
        # inputs so the backend embeds what the canvas graph sends.
        raw = str(
            inputs.get("heavy_chain") or inputs.get("light_chain") or inputs.get("sequence") or ""
        ).strip()

        model_size = str(inputs.get("model_size", "650M")).strip()
        pool_mode  = str(inputs.get("pool_mode",  "mean")).strip().lower()

        if is_multi_fasta(raw):
            return await self._invoke_batch(run_ctx, raw, model_size, pool_mode)
        return await self._invoke_single(run_ctx, raw, model_size, pool_mode)

    async def _invoke_batch(
        self,
        run_ctx: RunContext,
        fasta_text: str,
        model_size: str,
        pool_mode: str,
    ) -> dict[str, Any]:
        entries = parse_fasta(fasta_text)
        n = len(entries)
        await run_ctx.alog(
            f"ESM2-{model_size} batch: {n} sequences (pool={pool_mode})"
        )
        await run_ctx.alog(
            "First run downloads weights to ~/.cache/huggingface (~700 MB for 650M)"
        )

        embeddings: list[Any] = []

        for i, (name, seq) in enumerate(entries, 1):
            seq = _clean_seq(seq)
            if not seq:
                await run_ctx.alog(f"[{i}/{n}] {name}: empty, skipped")
                embeddings.append([])
                continue

            await run_ctx.alog(f"[{i}/{n}] {name} len={len(seq)}")
            cache_inputs = {"sequence": seq, "model_size": model_size, "pool_mode": pool_mode}
            cached = await self._cache.get(cache_inputs)
            if cached is not None:
                embeddings.append(cached.get("embedding", []))
                continue

            outputs = await run_tool_subprocess(
                tool_id="esm_embedding",
                inputs=cache_inputs,
                timeout=self.spec.runtime.timeout_seconds,
                on_log=run_ctx.alog,
                run_id=run_ctx.run_id,
            )
            await self._cache.put(cache_inputs, outputs,
                                  run_id=run_ctx.run_id, node_id=run_ctx.node_id)
            embeddings.append(outputs.get("embedding", []))

        await run_ctx.alog(f"ESM2 batch done — {n} sequences")
        first = next((e for e in embeddings if e), [])
        last_dim = "?"
        if embeddings:
            last_cache = {"sequence": entries[-1][1], "model_size": model_size, "pool_mode": pool_mode}
            last_out = await self._cache.get(last_cache)
            if last_out:
                last_dim = last_out.get("metadata", {}).get("embedding_dim", "?")
        return {
            "embedding":  first,
            "embeddings": embeddings,
            "count":      n,
            "metadata":   {"batch": True, "count": n, "model_size": model_size, "embedding_dim": last_dim},
        }

    async def _invoke_single(
        self,
        run_ctx: RunContext,
        raw: str,
        model_size: str,
        pool_mode: str,
    ) -> dict[str, Any]:
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = _clean_seq(str(raw))

        if not sequence:
            raise ValueError("ESM2 requires a sequence (sequence, heavy_chain, or light_chain)")

        if "/" in raw:
            await run_ctx.alog("Multi-chain sequence — using first chain only")
        if "X" in raw:
            await run_ctx.alog("Replaced non-standard residues X→A for ESM2 compatibility")

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
