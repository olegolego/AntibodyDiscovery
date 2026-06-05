"""Mutation Composer adapter — calls tools/mutation_composer/run.py.

Uses the backend venv (stdlib only, no extra deps required).
"""
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"


class MutationComposerAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        # No caching: stochastic output — each call should produce a fresh sample.

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        original = str(inputs.get("original", "")).strip()
        frequencies = inputs.get("frequencies", {})
        num_sequences = int(inputs.get("num_sequences", 10))
        mode = str(inputs.get("mode", "weighted_random")).strip()
        max_mutations = int(inputs.get("max_mutations", 3))

        # Accept upstream heavy_chain when 'original' is not wired explicitly
        if not original:
            original = str(inputs.get("heavy_chain", "")).strip()

        # Accept mutation_profiler's output ports when 'frequencies' is not wired
        if not frequencies:
            for key in ("relative_frequencies", "absolute_frequencies"):
                v = inputs.get(key)
                if v:
                    frequencies = v
                    break

        if not original:
            raise ValueError("mutation_composer requires 'original' sequence")

        await run_ctx.alog(
            f"Mutation Composer: generating {num_sequences} candidates "
            f"(mode={mode}, max_mutations={max_mutations})..."
        )

        payload: dict[str, Any] = {
            "original": original,
            "frequencies": frequencies,
            "num_sequences": num_sequences,
            "mode": mode,
            "max_mutations": max_mutations,
        }

        outputs = await run_tool_subprocess(
            tool_id="mutation_composer",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_TOOL_PYTHON),
        )

        n_generated = len(outputs.get("sequences", []))
        await run_ctx.alog(f"Done — {n_generated} candidate sequences composed")
        return outputs
