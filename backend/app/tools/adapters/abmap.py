from typing import Any

from app.config import settings
from app.core.molecule_key import MoleculeKey
from app.models.tool_spec import ToolSpec
from app.tools.abmap_db import abmap_cache
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry


class AbMAPAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Accept "sequence" directly or heavy_chain/light_chain from sequence_input's generic out handle
        raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("light_chain") or ""
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = str(raw).strip()
        if not sequence:
            raise ValueError("AbMAP requires a sequence input (sequence, heavy_chain, or light_chain)")

        # ProteinMPNN uses '/' as chain separator and 'X' for masked/unusual residues
        if "/" in sequence:
            sequence = sequence.split("/")[0]
        if "X" in sequence:
            sequence = sequence.replace("X", "A")

        default_chain = "H" if inputs.get("heavy_chain") and not inputs.get("sequence") else (
                        "L" if inputs.get("light_chain") and not inputs.get("sequence") else "H")
        chain_type    = str(inputs.get("chain_type", default_chain)).upper()
        task          = str(inputs.get("task", "structure"))
        embedding_type = str(inputs.get("embedding_type", "fixed"))
        num_mutations = int(inputs.get("num_mutations", 10))

        # (VH, VL) context — use heavy_chain/light_chain if available upstream,
        # otherwise the sequence itself is the key (single-chain embed).
        vh = str(inputs.get("heavy_chain") or (sequence if chain_type == "H" else "")).strip()
        vl = str(inputs.get("light_chain") or (sequence if chain_type == "L" else "")).strip()
        mol_key = MoleculeKey(vh, vl)

        await run_ctx.alog(
            f"Submitting AbMAP embedding request "
            f"(chain={chain_type}, task={task}, type={embedding_type}, len={len(sequence)}) "
            f"[key={mol_key.short()}]"
        )

        # ── Cache check ───────────────────────────────────────────────────────
        cached = await abmap_cache.get(
            vh, vl,
            chain_type=chain_type,
            task=task,
            embedding_type=embedding_type,
            num_mutations=num_mutations,
        )
        if cached is not None:
            shape = (cached.get("metadata") or {}).get("embedding_shape", "?")
            await run_ctx.alog(f"AbMAP cache hit — shape {shape} [key={mol_key.short()}]")
            return cached

        # ── Call AbMAP server ─────────────────────────────────────────────────
        try:
            data = await post_with_retry(
                settings.abmap_url,
                "/embed",
                {
                    "sequence":       sequence,
                    "chain_type":     chain_type,
                    "task":           task,
                    "embedding_type": embedding_type,
                    "num_mutations":  num_mutations,
                },
                tool_name="AbMAP",
                timeout=1800,
                on_log=run_ctx.alog,
            )
        except RuntimeError as exc:
            # AbMAP failures are non-fatal — bad CDR numbering, server hiccup, etc.
            # Log a warning and return an empty result so the pipeline continues.
            await run_ctx.alog(f"⚠ AbMAP skipped: {exc}")
            return {"embedding": [], "metadata": {"error": str(exc), "skipped": True}}

        result = {
            "embedding": data["embedding"],
            "metadata":  data["metadata"],
        }

        # ── Persist to DB ─────────────────────────────────────────────────────
        await abmap_cache.put(
            vh, vl,
            chain_type=chain_type,
            task=task,
            embedding_type=embedding_type,
            num_mutations=num_mutations,
            result=result,
            run_id=run_ctx.run_id,
            node_id=run_ctx.node_id,
        )

        shape = data.get("metadata", {}).get("embedding_shape", "?")
        await run_ctx.alog(f"AbMAP embedding complete — shape {shape} [saved to DB]")
        return result
