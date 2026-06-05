"""DNA Encoder adapter — codon-optimizes protein sequences for a target organism.

Pattern B (subprocess): run.py lives in tools/dna_encoder/run.py and executes
in the backend venv (no tool-specific deps needed).
"""
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"


class DNAEncoderAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="dna_encoder", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Accept upstream heavy_chain / light_chain when 'sequence' is not wired explicitly
        if not str(inputs.get("sequence", "")).strip():
            parts = []
            for key in ("heavy_chain", "light_chain"):
                v = str(inputs.get(key, "")).strip()
                if v:
                    parts.append(f">{key}\n{v}")
            if parts:
                inputs = {**inputs, "sequence": "\n".join(parts)}

        organism = str(inputs.get("organism", "EC")).upper()
        n_seqs = str(inputs.get("sequence", "")).count(">") or 1

        await run_ctx.alog(f"DNA Encoder: organism={organism}, ~{n_seqs} sequence(s)")

        cached = self._cache.get(inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        outputs = await run_tool_subprocess(
            tool_id="dna_encoder",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_TOOL_PYTHON),
        )

        if outputs.get("error"):
            await run_ctx.alog(f"DNA Encoder error: {outputs['error']}")
            raise RuntimeError(f"DNA Encoder failed: {outputs['error']}")

        gc = outputs.get("gc_content", [])
        if gc:
            summary = ", ".join(
                f"{r['id']}: {r['gc_percent']}% GC" for r in gc[:3]
            )
            if len(gc) > 3:
                summary += f" (+{len(gc) - 3} more)"
            await run_ctx.alog(f"DNA Encoder done — {summary}")
        else:
            await run_ctx.alog("DNA Encoder done")

        self._cache.put(inputs, outputs)
        return outputs
