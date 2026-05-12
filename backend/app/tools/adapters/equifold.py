"""EquiFold adapter — fast antibody structure prediction via subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.molecule_cache import MoleculeResultCache
from app.tools.subprocess_runner import run_tool_subprocess

_AA = set("ACDEFGHIKLMNPQRSTVWY")


def _clean_sequence(raw: str) -> str:
    lines = [l.strip() for l in str(raw).splitlines() if not l.startswith(">")]
    return "".join(lines).upper().replace(" ", "")


class EquiFoldAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="equifold", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        heavy = _clean_sequence(inputs.get("heavy_chain", ""))
        light = _clean_sequence(inputs.get("light_chain", "") or "")

        if not heavy:
            raise ValueError("heavy_chain is required")

        cache_key = {"heavy_chain": heavy, "light_chain": light}
        cached = await self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored EquiFold result")
            return cached

        await run_ctx.alog(
            f"EquiFold structure prediction — H={len(heavy)} AA"
            + (f", L={len(light)} AA" if light else " (VH only)")
        )

        outputs = await run_tool_subprocess(
            tool_id="equifold",
            inputs={"heavy_chain": heavy, "light_chain": light},
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
        )

        await run_ctx.alog("Done")
        await self._cache.put(cache_key, outputs, run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
