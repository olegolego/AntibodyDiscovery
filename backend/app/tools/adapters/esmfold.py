from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry
from app.tools.molecule_cache import MoleculeResultCache


class ESMFoldAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = MoleculeResultCache(tool_id="esmfold", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("light_chain") or ""
        # ProteinMPNN outputs a list — take the best (first) sequence
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        sequence: str = str(raw).strip()
        if not sequence:
            raise ValueError("ESMFold requires a sequence input (sequence, heavy_chain, or light_chain)")

        cached = await self._cache.get({"sequence": sequence})
        if cached is not None:
            await run_ctx.alog(f"Cache hit — ESMFold (len={len(sequence)})")
            return cached

        await run_ctx.alog(f"Submitting sequence (len={len(sequence)}) to ESMFold at {settings.esmfold_url}")

        data = await post_with_retry(
            settings.esmfold_url,
            "/predict",
            {"sequence": sequence},
            tool_name="ESMFold",
            timeout=1800,
            on_log=run_ctx.alog,
        )

        await run_ctx.alog("ESMFold prediction complete")
        outputs = {
            "structure": data["pdb"],
            "plddt": data.get("plddt"),
        }
        await self._cache.put({"sequence": sequence}, outputs,
                              run_id=run_ctx.run_id, node_id=run_ctx.node_id)
        return outputs
