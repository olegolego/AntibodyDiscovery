"""PDBFixer adapter — calls tools/pdbfixer/run.py in its own venv.

pdbfixer requires openmm which can be tricky to install via pip alone.
setup.sh tries pip first; if that fails it guides the user toward a conda install.
The adapter looks for .venv (pip path) then conda env 'pdbfixer' (conda path).
"""
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

_TOOLS_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "tools"


def _find_pdbfixer_python() -> str | None:
    """Return python path for pdbfixer: .venv first, then conda env 'pdbfixer'."""
    venv_py = _TOOLS_DIR / "pdbfixer" / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    for root in _CONDA_ROOTS:
        py = Path(root) / "envs" / "pdbfixer" / "bin" / "python"
        if py.exists():
            return str(py)
    return None


class PDBFixerAdapter:
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
            raise ValueError("structure input is required (wire from ImmuneBuilder, AlphaFold, etc.)")

        python_path = _find_pdbfixer_python()
        if python_path is None:
            raise FileNotFoundError(
                "PDBFixer environment not found. "
                "Run: bash tools/pdbfixer/setup.sh"
            )

        payload = {
            "structure":            structure,
            "fix_missing_residues": bool(inputs.get("fix_missing_residues", True)),
            "fix_missing_atoms":    bool(inputs.get("fix_missing_atoms", True)),
            "remove_heterogens":    bool(inputs.get("remove_heterogens", True)),
            "add_hydrogens":        bool(inputs.get("add_hydrogens", False)),
            "ph":                   float(inputs.get("ph", 7.0)),
        }

        await run_ctx.alog("PDBFixer: cleaning structure…")

        outputs = await run_tool_subprocess(
            tool_id="pdbfixer",
            inputs=payload,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=python_path,
        )

        report = outputs.get("report", {})
        await run_ctx.alog(
            f"PDBFixer: done — "
            f"chains={report.get('chains', [])}, "
            f"+{report.get('missing_residues_added', 0)} residues, "
            f"+{report.get('missing_atoms_added', 0)} atoms, "
            f"-{report.get('heterogens_removed', 0)} HETATM"
        )

        return outputs
