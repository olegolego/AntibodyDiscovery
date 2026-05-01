#!/usr/bin/env python3
#!/usr/bin/env python3
# Force DGL pytorch backend before any imports that touch DGL
import os as _os; _os.environ.setdefault("DGLBACKEND", "pytorch")
"""RFdiffusion subprocess entry point. Reads JSON from stdin, writes JSON to stdout.

Expected inputs dict keys:
  target_pdb       : str  — PDB text (empty = unconditional design)
  hotspot_residues : str  — e.g. "A30,A33,A42" (only used with target_pdb)
  num_designs      : int  — number of backbones to generate
  num_residues     : int  — length of designed chain
  diffusion_steps  : int  — timesteps (15–200)
"""
import json
import os
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE      = Path(__file__).resolve().parent
_RFD_ROOT  = _HERE / "RFdiffusion"
_MODELS    = _HERE / "models"
_SCRIPT    = _RFD_ROOT / "scripts" / "run_inference.py"
_PYTHON    = Path(sys.executable)   # already running in the tool venv

# Patch NVTX (CUDA profiling stubs) to no-ops — required on CPU builds of PyTorch
# where torch.cuda.nvtx raises "NVTX functions not installed" at DGL import time.
try:
    import torch.cuda.nvtx as _nvtx  # noqa: E402
    _nvtx.range_push = lambda _s: None
    _nvtx.range_pop = lambda: None
except Exception:
    pass


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _is_fasta(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith(">"):
        return True
    first = stripped.splitlines()[0].upper().split()
    pdb_kw = {"ATOM", "HETATM", "HEADER", "REMARK", "MODEL", "END"}
    return bool(first) and first[0] not in pdb_kw and all(
        c in "ACDEFGHIKLMNPQRSTVWYX \t\n" for c in stripped
    )


def _run(inputs: dict) -> dict:
    raw_target      = (inputs.get("target_pdb") or inputs.get("target") or "").strip()
    hotspot_res     = (inputs.get("hotspot_residues") or "").strip()
    num_designs     = max(1, int(inputs.get("num_designs", 1)))
    num_residues    = max(10, int(inputs.get("num_residues", 80)))
    diffusion_steps = max(15, min(200, int(inputs.get("diffusion_steps", 50))))

    if raw_target and _is_fasta(raw_target):
        raise ValueError(
            "target_pdb looks like a FASTA sequence — RFdiffusion needs a 3D structure. "
            "Run the target through AlphaFold or ESMFold first and connect the 'structure' output."
        )

    binder_mode = bool(raw_target)

    if not _SCRIPT.exists():
        raise FileNotFoundError(
            f"RFdiffusion not found at {_RFD_ROOT}.\n"
            "Run tools/rfdiffusion/setup.sh first."
        )
    if not any(_MODELS.glob("*.pt")):
        raise FileNotFoundError(
            f"No model weights found in {_MODELS}.\n"
            "Run tools/rfdiffusion/setup.sh to download weights."
        )

    with tempfile.TemporaryDirectory(prefix="rfd_") as tmp:
        tmpdir = Path(tmp)
        out_prefix = str(tmpdir / "design")

        overrides = [
            f"inference.output_prefix={out_prefix}",
            f"inference.model_directory_path={_MODELS}",
            f"inference.num_designs={num_designs}",
            f"diffuser.T={diffusion_steps}",
            "inference.cautious=False",
        ]

        if binder_mode:
            target_path = tmpdir / "target.pdb"
            target_path.write_text(raw_target)
            overrides += [
                f"inference.input_pdb={target_path}",
                f"inference.ckpt_override_path={_MODELS}/Complex_base_ckpt.pt",
                f"contigmap.contigs=[{num_residues}-{num_residues}/0 A1-999]",
            ]
            if hotspot_res:
                overrides.append(f"ppi.hotspot_res=[{hotspot_res}]")
            _progress(f"Binder design | target set | hotspots={hotspot_res or 'none'}")
        else:
            overrides.append(f"contigmap.contigs=[{num_residues}-{num_residues}]")
            _progress("Unconditional backbone design")

        _progress(f"{num_designs} design(s) | {num_residues} residues | {diffusion_steps} steps")
        _progress("Launching RFdiffusion…")

        env = {**os.environ, "DGLBACKEND": "pytorch", "PYTHONUNBUFFERED": "1"}
        cmd = [str(_PYTHON), str(_SCRIPT)] + overrides

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(_RFD_ROOT), env=env,
        )
        for raw_line in proc.stdout:  # type: ignore[union-attr]
            line = raw_line.rstrip()
            if any(k in line for k in ("Timestep", "Making design", "INFO", "Error", "error", "Warning")):
                clean = line.split("] - ")[-1] if "] - " in line else line
                _progress(clean)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"RFdiffusion exited with code {proc.returncode}")

        pdb_files = sorted(tmpdir.glob("design_*.pdb"))
        if not pdb_files:
            raise RuntimeError("RFdiffusion produced no PDB output files")

        pdbs = [f.read_text() for f in pdb_files]
        _progress(f"Generated {len(pdbs)} backbone(s)")

        meta: dict = {
            "num_designs": len(pdbs),
            "num_residues": num_residues,
            "diffusion_steps": diffusion_steps,
            "mode": "binder" if binder_mode else "unconditional",
            "hotspot_residues": hotspot_res or None,
        }
        for trb_path in sorted(tmpdir.glob("design_*.trb"))[:1]:
            try:
                trb = pickle.load(open(trb_path, "rb"))
                if "plddt" in trb:
                    meta["plddt"] = trb["plddt"]
                if "contigs" in trb:
                    meta["contigs"] = str(trb["contigs"])
            except Exception:
                pass

        backbone = pdbs[0] if len(pdbs) == 1 else "\n".join(
            f"MODEL {i + 1}\n{pdb}ENDMDL" for i, pdb in enumerate(pdbs)
        )
        return {"backbone": backbone, "metadata": meta}


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    import numpy as _np

    class _NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, _np.ndarray):
                return obj.tolist()
            if isinstance(obj, (_np.integer,)):
                return int(obj)
            if isinstance(obj, (_np.floating,)):
                return float(obj)
            return super().default(obj)

    json.dump(outputs, sys.stdout, cls=_NumpyEncoder)
    sys.stdout.flush()
