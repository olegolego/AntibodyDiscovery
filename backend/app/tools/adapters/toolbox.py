"""Stub adapter for toolbox (WIP) tools — custom DNN, diffusion designer, property predictor."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext

_ROADMAP: dict[str, str] = {
    "custom_dnn": (
        "Custom DNN is coming soon. Planned: configurable MLP/Transformer/CNN over "
        "ESM-2 embeddings for regression and classification tasks."
    ),
    "diffusion_design": (
        "Diffusion Designer is coming soon. Planned: fine-tune or sample from "
        "RFdiffusion/FrameDiff/Chroma with custom noise schedules and motif constraints."
    ),
    "property_predictor": (
        "Property Predictor is coming soon. Planned: ESM-2–backed predictors for "
        "affinity, stability, developability, and immunogenicity."
    ),
}


class ToolboxAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        msg = _ROADMAP.get(self.spec.id, f"'{self.spec.name}' is not yet implemented.")
        run_ctx.log(f"[WIP] {msg}")
        raise NotImplementedError(msg)
