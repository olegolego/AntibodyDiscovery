from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry
from app.tools.molecule_cache import MoleculeResultCache


class ProteinMPNNAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="proteinmpnn", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        cache_inputs = {
            "structure":      inputs["structure"],
            "num_sequences":  inputs.get("num_sequences", 8),
            "sampling_temp":  inputs.get("sampling_temp", 0.1),
        }

        cached = await self._cache.get(cache_inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored ProteinMPNN result")
            return cached

        await run_ctx.alog(f"Submitting to ProteinMPNN at {settings.proteinmpnn_url}")

        data = await post_with_retry(
            settings.proteinmpnn_url,
            "/design",
            cache_inputs,
            tool_name="ProteinMPNN",
            timeout=300,
            on_log=run_ctx.alog,
        )

        await run_ctx.alog("ProteinMPNN design complete")
        outputs = {"sequence": data["sequences"], "scores": data.get("scores")}
        await self._cache.put(cache_inputs, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
