"""AbLang adapter — antibody language model embeddings via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess


class AbLangAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="ablang", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("light_chain") or ""
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = str(raw).strip()
        default_chain = "H" if inputs.get("heavy_chain") and not inputs.get("sequence") else (
                        "L" if inputs.get("light_chain") and not inputs.get("sequence") else "H")
        chain_type = str(inputs.get("chain_type", default_chain)).upper()
        mode = str(inputs.get("mode", "seqcoding")).lower()

        if not sequence:
            raise ValueError("sequence is required (sequence, heavy_chain, or light_chain)")

        # ProteinMPNN uses '/' as chain separator and 'X' for masked/unusual residues
        if "/" in sequence:
            sequence = sequence.split("/")[0]
            await run_ctx.alog("Multi-chain sequence: using first chain only")
        if "X" in sequence:
            sequence = sequence.replace("X", "A")
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
