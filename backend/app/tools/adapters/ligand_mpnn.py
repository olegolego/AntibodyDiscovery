"""LigandMPNN adapter — ligand-aware inverse folding.

Calls tools/ligand_mpnn/run.py via the tool's own .venv (dauparas/LigandMPNN).
Pattern B (subprocess). See docs/adding-tools.md § Pattern B.

Setup: bash tools/ligand_mpnn/setup.sh
"""
import json
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

_TOOL_DIR = Path(__file__).parents[3] / "tools" / "ligand_mpnn"
# Use the tool's own venv if available (has torch + prody); fall back to backend venv
_VENV_PYTHON = _TOOL_DIR / ".venv" / "bin" / "python"
_TOOL_PYTHON = Path(os.getenv("LIGAND_MPNN_PYTHON", str(_VENV_PYTHON)))


class LigandMPNNAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="ligand_mpnn", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        structure = str(inputs.get("structure", "") or "").strip()
        num_sequences = int(inputs.get("num_sequences", 10) or 10)
        redesigned_raw = inputs.get("redesigned", [])
        sampling_temp = float(inputs.get("sampling_temp", 0.1) or 0.1)

        if isinstance(redesigned_raw, str):
            try:
                redesigned_list = json.loads(redesigned_raw)
            except json.JSONDecodeError:
                redesigned_list = []
        else:
            redesigned_list = redesigned_raw if isinstance(redesigned_raw, list) else []

        cache_key: dict[str, Any] = {
            "structure": structure,
            "num_sequences": num_sequences,
            "redesigned": redesigned_list,
            "sampling_temp": sampling_temp,
        }

        cached = self._cache.get(cache_key)
        if cached is not None:
            await run_ctx.alog("Cache hit — returning stored LigandMPNN result")
            return cached

        pocket_msg = (
            f"{len(redesigned_list)} pocket residues"
            if redesigned_list
            else "full sequence"
        )
        await run_ctx.alog(
            f"LigandMPNN: designing {num_sequences} sequences "
            f"({pocket_msg}, temp={sampling_temp})"
        )

        python_path = str(_TOOL_PYTHON) if _TOOL_PYTHON.exists() else None
        outputs = await run_tool_subprocess(
            tool_id="ligand_mpnn",
            inputs=cache_key,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=python_path,
        )

        n_seqs = len(outputs.get("sequences", []))
        await run_ctx.alog(f"LigandMPNN done — {n_seqs} sequences generated")

        self._cache.put(cache_key, outputs)
        return outputs
