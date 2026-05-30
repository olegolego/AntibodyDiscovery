"""Compound Library adapter — runs tools/compound_library/run.py via backend venv.

Creates a compound library from a SMILES dictionary or list.
From BioPipelines (Quargnali & Rivera-Fuentes 2026), Application 3.
"""
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"


class CompoundLibraryAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="compound_library", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        smiles_dict    = inputs.get("smiles_dict")
        compounds_list = inputs.get("compounds_list")

        payload = {
            "smiles_dict":    smiles_dict,
            "compounds_list": compounds_list,
        }

        cached = self._cache.get(payload)
        if cached is not None:
            await run_ctx.alog("Compound Library: cache hit")
            return cached

        await run_ctx.alog("Compound Library: assembling compound library…")

        outputs = await run_tool_subprocess(
            tool_id="compound_library",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_TOOL_PYTHON),
        )

        if outputs.get("error"):
            raise RuntimeError(f"compound_library failed: {outputs['error']}")

        n = outputs.get("n_compounds", 0)
        await run_ctx.alog(f"Compound Library: {n} compound(s) ready")

        self._cache.put(payload, outputs)
        return outputs
