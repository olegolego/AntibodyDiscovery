"""RFdiffusion adapter — runs tools/rfdiffusion/run.py via run_tool_subprocess."""
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.subprocess_runner import run_tool_subprocess


def _is_fasta(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith(">"):
        return True
    first = stripped.splitlines()[0].upper().split() if stripped else []
    pdb_kw = {"ATOM", "HETATM", "HEADER", "REMARK", "MODEL", "END"}
    return bool(first) and first[0] not in pdb_kw and all(
        c in "ACDEFGHIKLMNPQRSTVWYX \t\n" for c in stripped
    )


class RFdiffusionAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw_target = (inputs.get("target_pdb", "") or inputs.get("target", "") or "").strip()

        if raw_target and _is_fasta(raw_target):
            raise ValueError(
                "target_pdb looks like a FASTA sequence — RFdiffusion needs a 3D structure. "
                "Run the target through AlphaFold or ESMFold first and connect the 'structure' output."
            )

        num_designs     = max(1, int(inputs.get("num_designs", 1)))
        num_residues    = max(10, int(inputs.get("num_residues", 80)))
        diffusion_steps = max(15, min(200, int(inputs.get("diffusion_steps", 50))))
        binder_mode     = bool(raw_target)

        await run_ctx.alog(
            f"RFdiffusion | {'binder' if binder_mode else 'unconditional'} | "
            f"{num_designs} design(s) | {num_residues} residues | {diffusion_steps} steps"
        )

        outputs = await run_tool_subprocess(
            tool_id="rfdiffusion",
            inputs={
                "target_pdb":       raw_target,
                "hotspot_residues": (inputs.get("hotspot_residues") or "").strip(),
                "num_designs":      num_designs,
                "num_residues":     num_residues,
                "diffusion_steps":  diffusion_steps,
            },
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,
            run_id=run_ctx.run_id,
            python_path=None,   # uses tools/rfdiffusion/.venv/bin/python automatically
        )

        await run_ctx.alog(f"RFdiffusion complete — backbone ready")
        return outputs
