"""RFdiffusion adapter — runs local RFdiffusion via subprocess in its dedicated venv."""
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext

# Paths relative to the project root
_PROJECT_ROOT = Path(__file__).parents[4]
_RFD_ROOT = _PROJECT_ROOT / "tools" / "rfdiffusion" / "RFdiffusion"
_RFD_VENV_PYTHON = _PROJECT_ROOT / "tools" / "rfdiffusion" / "venv" / "bin" / "python3"
_RFD_MODELS = _PROJECT_ROOT / "tools" / "rfdiffusion" / "models"
_RFD_SCRIPT = _RFD_ROOT / "scripts" / "run_inference.py"


def _is_fasta(text: str) -> bool:
    """Heuristic: starts with '>' header or looks like a bare AA sequence."""
    stripped = text.strip()
    if stripped.startswith(">"):
        return True
    # bare sequence: only AA letters + whitespace, no PDB keywords
    first_line = stripped.splitlines()[0].upper()
    pdb_keywords = {"ATOM", "HETATM", "HEADER", "REMARK", "MODEL", "END"}
    return first_line.split()[0] not in pdb_keywords and all(
        c in "ACDEFGHIKLMNPQRSTVWYX \t\n" for c in stripped
    )


def _resolve_target(raw: str) -> str:
    """
    Accept either PDB text or a FASTA sequence as the target input.
    Returns PDB text, or raises ValueError with a clear message if FASTA is given
    (RFdiffusion needs 3D coordinates — fold the target first with AlphaFold/ESMFold).
    """
    if not raw:
        return ""
    if _is_fasta(raw):
        raise ValueError(
            "Target input looks like a FASTA sequence, but RFdiffusion requires a "
            "3D structure (PDB format). Please run the target through AlphaFold or "
            "ImmuneBuilder first and connect the 'structure' output here."
        )
    return raw


class RFdiffusionAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        raw_target: str = (inputs.get("target_pdb", "") or inputs.get("target", "") or "").strip()
        target_pdb: str = _resolve_target(raw_target)
        hotspot_res: str = (inputs.get("hotspot_residues", "") or "").strip()
        num_designs: int = max(1, int(inputs.get("num_designs", 1)))
        num_residues: int = max(10, int(inputs.get("num_residues", 80)))
        diffusion_steps: int = max(15, min(200, int(inputs.get("diffusion_steps", 50))))

        binder_mode = bool(target_pdb.strip())

        with tempfile.TemporaryDirectory(prefix="rfd_") as tmpdir:
            tmpdir = Path(tmpdir)

            # Write target PDB if provided
            target_path = None
            if binder_mode:
                target_path = tmpdir / "target.pdb"
                target_path.write_text(target_pdb)

            out_prefix = str(tmpdir / "design")

            # Build hydra overrides
            overrides = [
                f"inference.output_prefix={out_prefix}",
                f"inference.model_directory_path={_RFD_MODELS}",
                f"inference.num_designs={num_designs}",
                f"diffuser.T={diffusion_steps}",
                "inference.cautious=False",  # always overwrite in our managed tmpdir
            ]

            if binder_mode:
                overrides += [
                    f"inference.input_pdb={target_path}",
                    f"inference.ckpt_override_path={_RFD_MODELS}/Complex_base_ckpt.pt",
                    f"contigmap.contigs=[{num_residues}-{num_residues}/0 A1-999]",
                ]
                if hotspot_res:
                    overrides.append(f"ppi.hotspot_res=[{hotspot_res}]")
                run_ctx.log(f"Binder design | target={target_path.name} hotspots={hotspot_res or 'none'}")
            else:
                overrides.append(f"contigmap.contigs=[{num_residues}-{num_residues}]")
                run_ctx.log("Unconditional backbone design")

            run_ctx.log(
                f"{num_designs} design(s) | {num_residues} residues | {diffusion_steps} steps"
            )

            cmd = [
                str(_RFD_VENV_PYTHON),
                str(_RFD_SCRIPT),
            ] + overrides

            env = {**os.environ, "DGLBACKEND": "pytorch"}

            run_ctx.log("Launching RFdiffusion…")

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=str(_RFD_ROOT),
                env=env,
            )

            # Stream logs in real-time, filter to useful lines
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.rstrip()
                if any(k in line for k in ("Timestep", "Making design", "INFO", "Error", "error")):
                    # Strip hydra log prefix for cleanliness
                    clean = line.split("] - ")[-1] if "] - " in line else line
                    run_ctx.log(clean)

            proc.wait()
            if proc.returncode != 0:
                raise RuntimeError(f"RFdiffusion exited with code {proc.returncode}")

            # Collect all output PDB files
            pdb_files = sorted(tmpdir.glob("design_*.pdb"))
            if not pdb_files:
                raise RuntimeError("RFdiffusion produced no PDB output files")

            # Read all designs — concatenate if multiple, return first as primary
            pdbs = [f.read_text() for f in pdb_files]
            run_ctx.log(f"Generated {len(pdbs)} backbone(s)")

            # Collect metadata from .trb files (hydra trajectory info)
            meta: dict[str, Any] = {
                "num_designs": len(pdbs),
                "num_residues": num_residues,
                "diffusion_steps": diffusion_steps,
                "mode": "binder" if binder_mode else "unconditional",
                "hotspot_residues": hotspot_res or None,
            }
            trb_files = sorted(tmpdir.glob("design_*.trb"))
            if trb_files:
                import pickle
                try:
                    trb = pickle.load(open(trb_files[0], "rb"))
                    # plddt-like scores stored in trb
                    if "plddt" in trb:
                        meta["plddt"] = trb["plddt"]
                    if "con_ref_pdb_idx" in trb:
                        meta["contigs"] = str(trb.get("contigs", ""))
                except Exception:
                    pass

            # Primary backbone = first design; all designs concatenated for multi-design runs
            backbone = pdbs[0] if len(pdbs) == 1 else "\n".join(
                f"MODEL {i+1}\n{pdb}ENDMDL" for i, pdb in enumerate(pdbs)
            )

            return {"backbone": backbone, "metadata": meta}
