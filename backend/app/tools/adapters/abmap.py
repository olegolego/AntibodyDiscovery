from typing import Any

from app.config import settings
from app.core.molecule_key import MoleculeKey
from app.models.tool_spec import ToolSpec
from app.tools.abmap_db import abmap_cache
from app.tools.base import RunContext
from app.tools.fasta_utils import is_multi_fasta, parse_fasta
from app.tools.http_tool import post_with_retry


def _clean_seq(seq: str) -> str:
    if "/" in seq:
        seq = seq.split("/")[0]
    if "X" in seq:
        seq = seq.replace("X", "A")
    return seq.strip()


class AbMAPAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        seq = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("candidate_sequences")
        if isinstance(seq, list) and seq:
            return await self._invoke_candidates(inputs, run_ctx, seq)

        vh_raw = str(seq or "").strip()
        vl_raw = str(inputs.get("light_chain") or "").strip()

        if is_multi_fasta(vh_raw):
            return await self._invoke_batch(inputs, run_ctx, vh_raw, vl_raw)
        return await self._invoke_single(inputs, run_ctx)

    async def _invoke_candidates(
        self,
        inputs: dict[str, Any],
        run_ctx: RunContext,
        sequences: list[str],
    ) -> dict[str, Any]:
        """Embed a list of VH sequences, return candidate_embeddings = {seq: vec}."""
        chain_type     = str(inputs.get("chain_type", "H")).upper()
        task           = str(inputs.get("task", "structure"))
        embedding_type = str(inputs.get("embedding_type", "fixed"))
        num_mutations  = int(inputs.get("num_mutations", 10))

        unique_seqs = list(dict.fromkeys(s.strip() for s in sequences if s and s.strip()))
        n = len(unique_seqs)
        await run_ctx.alog(f"AbMAP candidates: embedding {n} sequences")

        candidate_embeddings: dict[str, list] = {}
        errors: list[str] = []

        for i, seq in enumerate(unique_seqs, 1):
            clean = _clean_seq(seq)
            cached = await abmap_cache.get(
                clean, "", chain_type=chain_type, task=task,
                embedding_type=embedding_type, num_mutations=num_mutations,
            )
            if cached is not None:
                emb = cached.get("embedding", [])
                if emb:
                    candidate_embeddings[seq] = emb
                    continue

            try:
                data = await post_with_retry(
                    settings.abmap_url, "/embed",
                    {"sequence": clean, "chain_type": chain_type, "task": task,
                     "embedding_type": embedding_type, "num_mutations": num_mutations},
                    tool_name="AbMAP", timeout=300, on_log=run_ctx.alog,
                )
            except RuntimeError as exc:
                errors.append(f"seq_{i}: {exc}")
                await run_ctx.alog(f"  [{i}/{n}] failed: {exc}")
                continue

            emb = data.get("embedding", [])
            if emb:
                candidate_embeddings[seq] = emb
                await abmap_cache.put(
                    clean, "", chain_type=chain_type, task=task,
                    embedding_type=embedding_type, num_mutations=num_mutations,
                    result=data, run_id=run_ctx.run_id, node_id=run_ctx.node_id,
                )

        await run_ctx.alog(
            f"AbMAP candidates done — {len(candidate_embeddings)}/{n} embedded"
        )
        return {
            "candidate_embeddings": candidate_embeddings,
            "embedding": list(candidate_embeddings.values())[0] if candidate_embeddings else [],
            "embeddings": list(candidate_embeddings.values()),
            "count": len(candidate_embeddings),
            "metadata": {"batch": True, "count": n, "errors": errors},
        }

    async def _invoke_batch(
        self,
        inputs: dict[str, Any],
        run_ctx: RunContext,
        vh_raw: str,
        vl_raw: str,
    ) -> dict[str, Any]:
        vh_entries = parse_fasta(vh_raw)
        vl_entries = parse_fasta(vl_raw) if vl_raw else []
        n = len(vh_entries)

        chain_type     = str(inputs.get("chain_type", "H")).upper()
        task           = str(inputs.get("task", "structure"))
        embedding_type = str(inputs.get("embedding_type", "fixed"))
        num_mutations  = int(inputs.get("num_mutations", 10))

        await run_ctx.alog(f"AbMAP batch: {n} sequences (chain={chain_type}, task={task})")

        embeddings: list[Any] = []
        errors: list[str] = []

        for i, (name, vh_seq) in enumerate(vh_entries, 1):
            vl_seq = _clean_seq(vl_entries[i - 1][1]) if i <= len(vl_entries) else ""
            vh_seq = _clean_seq(vh_seq)
            if not vh_seq:
                errors.append(f"[{i}/{n}] {name}: empty sequence, skipped")
                await run_ctx.alog(f"[{i}/{n}] {name}: empty, skipped")
                embeddings.append([])
                continue

            sequence = vh_seq if chain_type == "H" else vl_seq
            if not sequence:
                sequence = vh_seq

            mol_key = MoleculeKey(vh_seq, vl_seq)
            await run_ctx.alog(f"[{i}/{n}] {name} len={len(sequence)} [key={mol_key.short()}]")

            cached = await abmap_cache.get(
                vh_seq, vl_seq,
                chain_type=chain_type,
                task=task,
                embedding_type=embedding_type,
                num_mutations=num_mutations,
            )
            if cached is not None:
                embeddings.append(cached.get("embedding", []))
                continue

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
                await run_ctx.alog(f"[{i}/{n}] {name}: ⚠ skipped — {exc}")
                errors.append(str(exc))
                embeddings.append([])
                continue

            emb = data["embedding"]
            embeddings.append(emb)
            item_result = {"embedding": emb, "metadata": data["metadata"]}
            await abmap_cache.put(
                vh_seq, vl_seq,
                chain_type=chain_type,
                task=task,
                embedding_type=embedding_type,
                num_mutations=num_mutations,
                result=item_result,
                run_id=run_ctx.run_id,
                node_id=run_ctx.node_id,
            )

        await run_ctx.alog(
            f"AbMAP batch done — {len(embeddings) - len(errors)}/{n} succeeded"
        )
        return {
            "embedding":  embeddings[0] if embeddings else [],
            "embeddings": embeddings,
            "count":      n,
            "metadata":   {"batch": True, "count": n, "errors": errors},
        }

    async def _invoke_single(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("light_chain") or ""
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence = str(raw).strip()
        if not sequence:
            raise ValueError("AbMAP requires a sequence input (sequence, heavy_chain, or light_chain)")

        if "/" in sequence:
            sequence = sequence.split("/")[0]
        if "X" in sequence:
            sequence = sequence.replace("X", "A")

        default_chain = "H" if inputs.get("heavy_chain") and not inputs.get("sequence") else (
                        "L" if inputs.get("light_chain") and not inputs.get("sequence") else "H")
        chain_type     = str(inputs.get("chain_type", default_chain)).upper()
        task           = str(inputs.get("task", "structure"))
        embedding_type = str(inputs.get("embedding_type", "fixed"))
        num_mutations  = int(inputs.get("num_mutations", 10))

        vh = str(inputs.get("heavy_chain") or (sequence if chain_type == "H" else "")).strip()
        vl = str(inputs.get("light_chain") or (sequence if chain_type == "L" else "")).strip()
        mol_key = MoleculeKey(vh, vl)

        await run_ctx.alog(
            f"Submitting AbMAP embedding request "
            f"(chain={chain_type}, task={task}, type={embedding_type}, len={len(sequence)}) "
            f"[key={mol_key.short()}]"
        )

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
            await run_ctx.alog(f"⚠ AbMAP skipped: {exc}")
            return {"embedding": [], "metadata": {"error": str(exc), "skipped": True}}

        result = {
            "embedding": data["embedding"],
            "metadata":  data["metadata"],
        }

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
