from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext

# Maps tool id → adapter class (lazy-imported to avoid loading all deps at startup)
_ADAPTER_MAP = {
    "sequence_input": ("app.tools.adapters.echo", "EchoAdapter"),
    "target_input": ("app.tools.adapters.echo", "EchoAdapter"),
    "echo": ("app.tools.adapters.echo", "EchoAdapter"),
    "immunebuilder": ("app.tools.adapters.immunebuilder", "ImmuneBuilderAdapter"),
    "alphafold_monomer": ("app.tools.adapters.alphafold", "AlphaFoldAdapter"),
    "esmfold": ("app.tools.adapters.esmfold", "ESMFoldAdapter"),
    "abmap": ("app.tools.adapters.abmap", "AbMAPAdapter"),
    "rfdiffusion": ("app.tools.adapters.rfdiffusion", "RFdiffusionAdapter"),
    "proteinmpnn": ("app.tools.adapters.proteinmpnn", "ProteinMPNNAdapter"),
    "haddock3":          ("app.tools.adapters.haddock3",  "HADDOCK3Adapter"),
    "biophi":            ("app.tools.adapters.biophi",    "BioPhiAdapter"),
    "ablang":            ("app.tools.adapters.ablang",    "AbLangAdapter"),
    "equidock":          ("app.tools.adapters.equidock",  "EquiDockAdapter"),
    "compute":           ("app.tools.adapters.compute",   "ComputeAdapter"),
    "custom_dnn":        ("app.tools.adapters.toolbox",   "ToolboxAdapter"),
    "diffusion_design":  ("app.tools.adapters.toolbox",   "ToolboxAdapter"),
    "property_predictor":("app.tools.adapters.toolbox",   "ToolboxAdapter"),
}


async def dispatch_tool(
    spec: ToolSpec, inputs: dict[str, Any], ctx: RunContext
) -> dict[str, Any]:
    entry = _ADAPTER_MAP.get(spec.id)
    if entry is None:
        raise ValueError(f"No adapter registered for tool '{spec.id}'")

    module_path, class_name = entry
    import importlib
    module = importlib.import_module(module_path)
    adapter_cls = getattr(module, class_name)
    adapter = adapter_cls(spec)
    return await adapter.invoke(inputs, ctx)
