from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry


class ProteinMPNNAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        await run_ctx.alog(f"Submitting to ProteinMPNN at {settings.proteinmpnn_url}")

        data = await post_with_retry(
            settings.proteinmpnn_url,
            "/design",
            {
                "structure": inputs["structure"],
                "num_sequences": inputs.get("num_sequences", 8),
                "sampling_temp": inputs.get("sampling_temp", 0.1),
            },
            tool_name="ProteinMPNN",
            timeout=300,
            on_log=run_ctx.alog,
        )

        await run_ctx.alog("ProteinMPNN design complete")
        return {"sequence": data["sequences"], "scores": data.get("scores")}
