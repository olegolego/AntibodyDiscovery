"""Mutation Profiler adapter — calls tools/mutation_profiler/run.py.

Uses the backend venv (stdlib only, no extra deps required).
"""
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"


class MutationProfilerAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="mutation_profiler", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        original = str(inputs.get("original", "")).strip()
        mutants = inputs.get("mutants", [])

        if not original:
            raise ValueError("mutation_profiler requires 'original' sequence")

        # Normalize mutants to a list for cache key stability
        if isinstance(mutants, str):
            import json as _json
            try:
                mutants = _json.loads(mutants)
            except Exception:
                mutants = [mutants]

        n_mutants = len(mutants) if isinstance(mutants, list) else 0

        cache_key: dict[str, Any] = {
            "original": original,
            "mutants": mutants,
        }

        cached = self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored Mutation Profiler result")
            return cached

        await run_ctx.alog(
            f"Mutation Profiler: analyzing {n_mutants} variants against WT "
            f"(length {len(original)})..."
        )

        outputs = await run_tool_subprocess(
            tool_id="mutation_profiler",
            inputs=cache_key,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=str(_TOOL_PYTHON),
        )

        summary = outputs.get("mutation_summary", {})
        n_mutated = summary.get("n_mutated_positions", "?")
        await run_ctx.alog(
            f"Done — {n_mutated} mutated positions found across {n_mutants} sequences"
        )

        self._cache.put(cache_key, outputs)
        return outputs
