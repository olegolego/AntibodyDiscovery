from typing import Any

from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry


class AbMAPAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequence = str(inputs["sequence"]).strip()
        chain_type = str(inputs.get("chain_type", "H")).upper()
        task = str(inputs.get("task", "structure"))
        embedding_type = str(inputs.get("embedding_type", "fixed"))
        num_mutations = int(inputs.get("num_mutations", 10))

        await run_ctx.alog(
            f"Submitting AbMAP embedding request "
            f"(chain={chain_type}, task={task}, type={embedding_type}, len={len(sequence)})"
        )

        data = await post_with_retry(
            settings.abmap_url,
            "/embed",
            {
                "sequence": sequence,
                "chain_type": chain_type,
                "task": task,
                "embedding_type": embedding_type,
                "num_mutations": num_mutations,
            },
            tool_name="AbMAP",
            timeout=1800,
            on_log=run_ctx.alog,
        )

        shape = data.get("metadata", {}).get("embedding_shape", "?")
        await run_ctx.alog(f"AbMAP embedding complete — shape {shape}")
        return {
            "embedding": data["embedding"],
            "metadata": data["metadata"],
        }
