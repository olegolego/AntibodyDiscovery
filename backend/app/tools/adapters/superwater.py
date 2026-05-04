"""SuperWater adapter — calls tools/superwater/run.py via the conda 'superwater' env."""
import os
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess

_CONDA_ROOTS = [
    os.path.expanduser("~/miniforge3"),
    os.path.expanduser("~/mambaforge"),
    os.path.expanduser("~/miniconda3"),
    os.path.expanduser("~/anaconda3"),
]


def _find_superwater_python() -> str | None:
    """Return path to the conda superwater env python, or None if not set up."""
    for root in _CONDA_ROOTS:
        py = Path(root) / "envs" / "superwater" / "bin" / "python"
        if py.exists():
            return str(py)
    return None


class SuperWaterAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        # Accept structure from common upstream port names
        structure = inputs.get("structure") or inputs.get("fixed_structure")
        if not structure:
            for k, v in inputs.items():
                if isinstance(v, str) and "ATOM" in v:
                    structure = v
                    break

        if not structure or "ATOM" not in str(structure):
            raise ValueError(
                "structure input is required (wire from PDBFixer, ImmuneBuilder, etc.)"
            )

        water_ratio = float(inputs.get("water_ratio", 1.0))
        cap         = float(inputs.get("cap", 0.1))

        python_path = _find_superwater_python()
        if python_path is None:
            raise FileNotFoundError(
                "SuperWater conda environment not found. "
                "Run: bash tools/superwater/setup.sh"
            )

        payload = {
            "structure":   structure,
            "water_ratio": water_ratio,
            "cap":         cap,
        }

        await run_ctx.alog(
            f"SuperWater: predicting water positions "
            f"(ratio={water_ratio}, cap={cap})…"
        )
        await run_ctx.alog(
            "SuperWater runs ESM2 embedding + diffusion inference — expect 2–10 min on CPU."
        )

        outputs = await run_tool_subprocess(
            tool_id="superwater",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=python_path,
        )

        wc = outputs.get("water_count", {})
        await run_ctx.alog(
            f"SuperWater: placed {wc.get('waters_placed', '?')} water molecules"
        )

        return outputs
