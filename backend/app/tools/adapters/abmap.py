"""AbMAP adapter — HTTP call to tools/abmap/server.py /embed_pairs."""
from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.abmap_db import abmap_cache
from app.tools.base import RunContext
from app.tools.embedding_utils import parse_sequences
from app.tools.http_tool import post_with_retry


class AbMAPAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequences      = parse_sequences(inputs)
        task           = str(inputs.get("task",           "structure"))
        embedding_type = str(inputs.get("embedding_type", "fixed"))
        num_mutations  = int(inputs.get("num_mutations",  10))

        n = len(sequences)
        await run_ctx.alog(
            f"AbMAP: {n} pair(s), task={task}, type={embedding_type}, k={num_mutations}"
        )

        # Per-pair cache check — skip pairs already cached
        uncached_sequences = []
        cached_results: dict[int, dict] = {}
        for i, pair in enumerate(sequences):
            vh = pair.get("vh", "")
            vl = pair.get("vl") or ""
            hit = await abmap_cache.get(
                vh, vl, chain_type="H", task=task,
                embedding_type=embedding_type, num_mutations=num_mutations,
            )
            if hit is not None:
                cached_results[i] = {
                    "vh": vh, "vl": vl or None,
                    "emb_vh": hit.get("embedding", []),
                    "emb_vl": None,
                }
            else:
                uncached_sequences.append((i, pair))

        results: list[dict] = [{}] * n
        for idx, res in cached_results.items():
            results[idx] = res

        if uncached_sequences:
            await run_ctx.alog(
                f"AbMAP: {len(uncached_sequences)} pair(s) not cached — calling server"
            )
            payload_seqs = [pair for _, pair in uncached_sequences]
            data = await post_with_retry(
                settings.abmap_url,
                "/embed_pairs",
                {
                    "sequences":      payload_seqs,
                    "task":           task,
                    "embedding_type": embedding_type,
                    "num_mutations":  num_mutations,
                },
                tool_name="AbMAP",
                timeout=self.spec.runtime.timeout_seconds,
                on_log=run_ctx.alog,
            )
            for (orig_idx, pair), entry in zip(uncached_sequences, data["results"]):
                results[orig_idx] = entry
                await abmap_cache.put(
                    pair.get("vh", ""), pair.get("vl") or "",
                    chain_type="H", task=task,
                    embedding_type=embedding_type, num_mutations=num_mutations,
                    result={"embedding": entry.get("emb_vh", []), "metadata": data.get("metadata", {})},
                    run_id=run_ctx.run_id, node_id=run_ctx.node_id,
                )

        await run_ctx.alog(f"AbMAP done — {n} pair(s)")
        return {
            "n": n,
            "results": results,
            "metadata": {"task": task, "embedding_type": embedding_type},
        }
