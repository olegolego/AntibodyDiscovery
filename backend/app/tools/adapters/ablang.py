"""AbLang adapter — antibody language model embeddings via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.fasta_utils import is_multi_fasta, parse_fasta
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


def _clean_seq(seq: str, run_ctx: RunContext | None = None) -> str:
    if "/" in seq:
        seq = seq.split("/")[0]
    if "X" in seq:
        seq = seq.replace("X", "A")
    return seq.strip()


class AbLangAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="ablang", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw_vh = str(inputs.get("heavy_chain") or "").strip()
        raw_vl = str(inputs.get("light_chain") or "").strip()
        raw_seq = str(inputs.get("sequence") or "").strip()

        default_chain = "H" if raw_vh else ("L" if raw_vl else "H")
        chain_type = str(inputs.get("chain_type", default_chain)).upper()
        mode       = str(inputs.get("mode", "seqcoding")).lower()

        # Pick the relevant raw input for this chain. Wired upstream chain inputs
        # should override the tool's demo/default `sequence` param.
        primary_raw = (raw_vh if chain_type == "H" else raw_vl) or raw_vh or raw_vl or raw_seq

        if is_multi_fasta(primary_raw):
            return await self._invoke_batch(inputs, run_ctx, primary_raw, chain_type, mode)

        return await self._invoke_single(inputs, run_ctx, primary_raw, chain_type, mode)

    async def _invoke_batch(
        self,
        inputs: dict[str, Any],
        run_ctx: RunContext,
        fasta_text: str,
        chain_type: str,
        mode: str,
    ) -> dict[str, Any]:
        entries = parse_fasta(fasta_text)
        n = len(entries)
        await run_ctx.alog(f"AbLang batch: {n} sequences (chain={chain_type}, mode={mode})")

        embeddings: list[Any] = []

        for i, (name, seq) in enumerate(entries, 1):
            seq = _clean_seq(seq)
            if not seq:
                await run_ctx.alog(f"[{i}/{n}] {name}: empty, skipped")
                embeddings.append([])
                continue

            await run_ctx.alog(f"[{i}/{n}] {name} len={len(seq)}")
            cache_inputs = {"sequence": seq, "chain_type": chain_type, "mode": mode}
            cached = await self._cache.get(cache_inputs)
            if cached is not None:
                embeddings.append(cached.get("embedding") or cached.get("residue_embeddings") or [])
                continue

            outputs = await run_tool_subprocess(
                tool_id="ablang",
                inputs=cache_inputs,
                timeout=self.spec.runtime.timeout_seconds,
                on_log=run_ctx.alog,
                run_id=run_ctx.run_id,
            )
            await self._cache.put(cache_inputs, outputs,
                                  run_id=run_ctx.run_id, node_id=run_ctx.node_id)
            embeddings.append(outputs.get("embedding") or outputs.get("residue_embeddings") or [])

        await run_ctx.alog(f"AbLang batch done — {n} sequences")
        first = next((e for e in embeddings if e), [])
        return {
            "embedding":  first,
            "embeddings": embeddings,
            "count":      n,
            "metadata":   {"batch": True, "count": n, "chain_type": chain_type, "mode": mode},
        }

    async def _invoke_single(
        self,
        inputs: dict[str, Any],
        run_ctx: RunContext,
        primary_raw: str,
        chain_type: str,
        mode: str,
    ) -> dict[str, Any]:
        sequence = _clean_seq(primary_raw)
        if not sequence:
            raise ValueError("sequence is required (sequence, heavy_chain, or light_chain)")

        if "/" in str(inputs.get("heavy_chain") or inputs.get("light_chain") or ""):
            await run_ctx.alog("Multi-chain sequence: using first chain only")
        if "X" in str(inputs.get("heavy_chain") or inputs.get("light_chain") or ""):
            await run_ctx.alog("Replaced non-standard residues (X→A) for AbLang compatibility")

        cache_inputs = {"sequence": sequence, "chain_type": chain_type, "mode": mode}
        cached = await self._cache.get(cache_inputs)
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

        await self._cache.put(cache_inputs, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
