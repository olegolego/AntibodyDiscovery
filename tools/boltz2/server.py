#!/usr/bin/env python3
"""Boltz2 HTTP server — wraps the `boltz predict` CLI as a REST endpoint.

Start:
    pip install boltz[cuda]
    uvicorn server:app --host 0.0.0.0 --port 8010

Reference: https://github.com/jwohlwend/boltz
Paper: Passaro et al. 2025 — https://doi.org/10.1101/2025.06.14.659707
"""
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Boltz2 prediction server")

# Use the boltz CLI from whichever venv is running this server.
_BOLTZ_BIN = str(Path(sys.executable).parent / "boltz")

# Use all physical CPU cores for preprocessing and PyTorch CPU ops.
# OMP/MKL thread counts are inherited by the boltz subprocess.
_CPU_COUNT = multiprocessing.cpu_count()
_TORCH_ENV = {
    **os.environ,
    "OMP_NUM_THREADS":  str(_CPU_COUNT),
    "MKL_NUM_THREADS":  str(_CPU_COUNT),
    "OPENBLAS_NUM_THREADS": str(_CPU_COUNT),
    "NUMEXPR_NUM_THREADS":  str(_CPU_COUNT),
}
# Dataloader workers: use N-2 cores (leave 2 for main thread + GPU feed)
_NUM_WORKERS = max(1, _CPU_COUNT - 2)


class PredictRequest(BaseModel):
    sequence: str = ""           # heavy chain (or full sequence if no light chain)
    light_chain: str = ""        # VL sequence — if provided, added as chain L
    structure: str = ""          # PDB text — alternative to sequence for iterative pipelines
    ligand_smiles: str = ""
    ligand_name: str = "LIG"
    diffusion_samples: int = 1
    recycling_steps: int = 3
    use_msa_server: bool = True   # uses ColabFold MSA server; required for good accuracy


@app.get("/health")
def health():
    return {"status": "ok"}


def _build_yaml(req: PredictRequest, tmpdir: str) -> str:
    """Write a Boltz2 YAML input file and return its path."""
    # If structure (PDB) given, extract sequence from CA ATOM records
    sequence = req.sequence
    if not sequence and req.structure:
        aa_map = {
            "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
            "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
            "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
            "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
        }
        residues = {}
        for line in req.structure.splitlines():
            if line.startswith("ATOM") and line[12:16].strip() == "CA":
                resname = line[17:20].strip()
                resnum = int(line[22:26])
                residues[resnum] = aa_map.get(resname, "X")
        sequence = "".join(residues[k] for k in sorted(residues))

    if not sequence:
        raise ValueError("No protein sequence could be determined from inputs")

    # Strip FASTA headers if present in any chain
    def _strip_fasta(s: str) -> str:
        lines = [l.strip() for l in s.splitlines() if not l.startswith(">")]
        return "".join(lines)

    sequence = _strip_fasta(sequence)
    light = _strip_fasta(req.light_chain) if req.light_chain else ""

    yaml_lines = ["version: 1", "sequences:"]
    yaml_lines += [
        "  - protein:",
        "      id: H",
        f"      sequence: {sequence}",
    ]
    if light:
        yaml_lines += [
            "  - protein:",
            "      id: L",
            f"      sequence: {light}",
        ]
    if req.ligand_smiles:
        yaml_lines += [
            "  - ligand:",
            f"      id: {req.ligand_name}",
            f"      smiles: \"{req.ligand_smiles}\"",
        ]

    input_path = os.path.join(tmpdir, "input.yaml")
    with open(input_path, "w") as f:
        f.write("\n".join(yaml_lines) + "\n")
    return input_path


@app.post("/predict")
def predict(req: PredictRequest):
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            input_yaml = _build_yaml(req, tmpdir)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        out_dir = os.path.join(tmpdir, "output")

        # --accelerator gpu routes to MPS automatically on Apple Silicon
        # (PyTorch Lightning detects mps and uses it under "gpu")
        cmd = [
            _BOLTZ_BIN, "predict", input_yaml,
            "--out_dir", out_dir,
            "--output_format", "pdb",
            "--accelerator", "gpu",    # routes to MPS on Apple Silicon automatically
            "--num_workers", str(_NUM_WORKERS),          # CPU cores for data loading
            "--preprocessing-threads", str(_CPU_COUNT),  # CPU cores for MSA preprocessing
            "--diffusion_samples", str(req.diffusion_samples),
            "--recycling_steps", str(req.recycling_steps),
            "--override",
        ]
        if req.use_msa_server:
            cmd.append("--use_msa_server")

        result = subprocess.run(cmd, capture_output=True, text=True, env=_TORCH_ENV)

        # boltz exits 0 even when it skips a record — check for actual output
        pdb_files = sorted(Path(out_dir).glob("**/*.pdb"))
        if not pdb_files:
            stderr_tail = (result.stderr or "")[-2000:]
            raise HTTPException(
                status_code=500,
                detail=f"boltz predict produced no PDB output.\n{stderr_tail}",
            )

        pdb_text = pdb_files[0].read_text()

        # Confidence JSON — boltz outputs: confidence_score, ptm, complex_plddt, etc.
        conf_files = sorted(Path(out_dir).glob("**/*confidence*.json"))
        confidence = json.loads(conf_files[0].read_text()) if conf_files else {}

        # Affinity JSON — only present when a ligand SMILES was provided
        aff_files = sorted(Path(out_dir).glob("**/*affinity*.json"))
        affinity = json.loads(aff_files[0].read_text()) if aff_files else {}

        # pLDDT: boltz stores per-residue values in a .npz file; use complex_plddt
        # from the confidence JSON as a scalar (0-1 range, same as ESMFold).
        # Return as a one-element list so downstream adapters see a list[float].
        complex_plddt = confidence.get("complex_plddt")
        plddt: list = [complex_plddt] if complex_plddt is not None else []

        return {
            "structure": pdb_text,
            "binding_probability": affinity.get(
                "affinity_probability",
                confidence.get("confidence_score", 0.5),
            ),
            "binding_affinity": affinity.get("affinity_pred_value"),
            "plddt": plddt,
            "ptm":  confidence.get("ptm"),
            "iptm": confidence.get("iptm"),
        }
