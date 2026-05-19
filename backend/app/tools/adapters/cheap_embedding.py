"""CHEAP embedding adapter — HTTP call to tools/cheap_embedding/server.py."""
import os
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.fasta_utils import is_multi_fasta, parse_fasta
from app.tools.http_tool import post_with_retry
from app.tools.molecule_cache import MoleculeResultCache

_CHEAP_URL = os.getenv("CHEAP_EMBEDDING_URL", "http://localhost:8006")


def _clean_seq(seq: str) -> str:
    if "/" in seq:
        seq = seq.split("/")[0]
    if "X" in seq:
        seq = seq.replace("X", "A")
    return seq.strip()


class CHEAPEmbeddingAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="cheap_embedding", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Wired upstream chain inputs should override the tool's demo/default
        # `sequence` param.
        raw = str(
            inputs.get("heavy_chain") or inputs.get("light_chain") or inputs.get("sequence") or ""
        ).strip()

        shorten_factor = int(inputs.get("shorten_factor", 1))
        dim            = int(inputs.get("dim", 64))

        if is_multi_fasta(raw):
            return await self._invoke_batch(run_ctx, raw, shorten_factor, dim)
        return await self._invoke_single(run_ctx, raw, shorten_factor, dim)

    async def _invoke_batch(
        self,
        run_ctx: RunContext,
        fasta_text: str,
        shorten_factor: int,
        dim: int,
    ) -> dict[str, Any]:
        entries = parse_fasta(fasta_text)
        n = len(entries)
        await run_ctx.alog(
            f"CHEAP batch: {n} sequences (shorten={shorten_factor}, dim={dim})"
        )
        await run_ctx.alog(
            "First call loads ESMFold trunk (~4 GB, 30–90 s on CPU)"
        )

        embeddings: list[Any] = []

        for i, (name, seq) in enumerate(entries, 1):
            seq = _clean_seq(seq)
            if not seq:
                await run_ctx.alog(f"[{i}/{n}] {name}: empty, skipped")
                embeddings.append([])
                continue

            await run_ctx.alog(f"[{i}/{n}] {name} len={len(seq)}")
            cache_inputs = {"sequence": seq, "shorten_factor": shorten_factor, "dim": dim}
            cached = await self._cache.get(cache_inputs)
            if cached is not None:
                embeddings.append(cached.get("embedding", []))
                continue

            data = await post_with_retry(
                _CHEAP_URL,
                "/embed",
                {"sequence": seq, "shorten_factor": shorten_factor, "dim": dim},
                tool_name="CHEAP",
                timeout=self.spec.runtime.timeout_seconds,
                on_log=run_ctx.alog,
            )
            outputs = {
                "embedding":          data["embedding"],
                "residue_embeddings": data.get("residue_embeddings"),
                "metadata":           data["metadata"],
            }
            await self._cache.put(cache_inputs, outputs,
                                  run_id=run_ctx.run_id, node_id=run_ctx.node_id)
            embeddings.append(data["embedding"])

        await run_ctx.alog(f"CHEAP batch done — {n} sequences")
        first = next((e for e in embeddings if e), [])
        return {
            "embedding":  first,
            "embeddings": embeddings,
            "count":      n,
            "metadata":   {"batch": True, "count": n, "shorten_factor": shorten_factor, "dim": dim},
        }

    async def _invoke_single(
        self,
        run_ctx: RunContext,
        raw: str,
        shorten_factor: int,
        dim: int,
    ) -> dict[str, Any]:
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = _clean_seq(str(raw))

        if not sequence:
            raise ValueError("CHEAP requires a sequence (sequence, heavy_chain, or light_chain)")

        if "/" in raw:
            await run_ctx.alog("Multi-chain sequence — using first chain only")
        if "X" in raw:
            await run_ctx.alog("Replaced non-standard residues X→A")

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
