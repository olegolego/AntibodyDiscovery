"""Fuse adapter — creates fusion proteins from domain sequences and variable linkers.

Pattern B (subprocess): run.py lives in tools/fuse/run.py and executes in the
backend venv (stdlib only, no tool-specific deps needed).
"""
import json
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"


class FuseAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="fuse", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw_seqs = inputs.get("sequences", [])
        if isinstance(raw_seqs, str):
            try:
                raw_seqs = json.loads(raw_seqs)
            except Exception:
                pass

        # Accept upstream heavy_chain / light_chain when 'sequences' is not wired explicitly
        if not isinstance(raw_seqs, list) or len(raw_seqs) < 2:
            domain_seqs: list[str] = []
            for key in ("heavy_chain", "light_chain"):
                v = str(inputs.get(key, "")).strip()
                if v:
                    domain_seqs.append(v)
            # Also collect variant_1..N from cdr_mutator upstream
            for i in range(1, 10):
                v = inputs.get(f"variant_{i}")
                if v is None:
                    break
                seq = v.get("heavy_chain", "").strip() if isinstance(v, dict) else str(v).strip()
                if seq:
                    domain_seqs.append(seq)
            if len(domain_seqs) >= 2:
                raw_seqs = domain_seqs
                inputs = {**inputs, "sequences": domain_seqs}

        n_seqs = len(raw_seqs) if isinstance(raw_seqs, list) else "?"
        linker = str(inputs.get("linker", "GSG"))
        name = str(inputs.get("name", "fusion"))

        await run_ctx.alog(
            f"Fuse: {n_seqs} domain(s), linker='{linker}', name='{name}'"
        )

        cached = self._cache.get(inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        outputs = await run_tool_subprocess(
            tool_id="fuse",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_TOOL_PYTHON),
        )

        if outputs.get("error"):
            await run_ctx.alog(f"Fuse error: {outputs['error']}")
            raise RuntimeError(f"Fuse failed: {outputs['error']}")

        n_fusions = outputs.get("n_fusions", len(outputs.get("fusions", [])))
        await run_ctx.alog(f"Fuse done — {n_fusions} fusion variant(s) generated")

        self._cache.put(inputs, outputs)
        return outputs
