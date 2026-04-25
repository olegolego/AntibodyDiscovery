from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry


class ESMFoldAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequence: str = str(inputs["sequence"]).strip()
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
        return {
            "structure": data["pdb"],
            "plddt": data.get("plddt"),
        }
