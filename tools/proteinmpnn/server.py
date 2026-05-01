"""ProteinMPNN HTTP wrapper — calls protein_mpnn_run.py via subprocess."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ProteinMPNN")

_REPO = Path(os.getenv("PROTEINMPNN_REPO", "/proteinmpnn"))
_SCRIPT = _REPO / "protein_mpnn_run.py"
_PYTHON = Path(os.getenv("PROTEINMPNN_PYTHON", "python"))


@app.on_event("startup")
async def check_setup():
    if not _SCRIPT.exists():
        raise RuntimeError(f"ProteinMPNN script not found: {_SCRIPT}")
    print(f"ProteinMPNN ready — {_SCRIPT}")


class DesignRequest(BaseModel):
    structure: str        # PDB file content as string
    num_sequences: int = 8
    sampling_temp: float = 0.1


@app.post("/design")
async def design(req: DesignRequest):
    if not req.structure.strip():
        raise HTTPException(status_code=400, detail="structure (PDB text) is required")

    with tempfile.TemporaryDirectory(prefix="mpnn_") as tmpdir:
        tmpdir = Path(tmpdir)
        pdb_path = tmpdir / "input.pdb"
        out_dir  = tmpdir / "out"
        out_dir.mkdir()

        pdb_path.write_text(req.structure)

        cmd = [
            str(_PYTHON), str(_SCRIPT),
            "--pdb_path",          str(pdb_path),
            "--out_folder",        str(out_dir),
            "--num_seq_per_target", str(req.num_sequences),
            "--sampling_temp",     str(req.sampling_temp),
            "--seed",              "37",
            "--batch_size",        "1",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(_REPO),
        )
        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"ProteinMPNN failed:\n{result.stderr[-2000:]}",
            )

        # Parse the output FASTA — header format:
        # >T=0.10, sample=1, score=1.23, global_score=1.23, seq_recovery=0.45
        fasta_files = list(out_dir.rglob("*.fa")) + list(out_dir.rglob("*.fasta"))
        if not fasta_files:
            raise HTTPException(status_code=500, detail="ProteinMPNN produced no FASTA output")

        sequences: list[str] = []
        scores: list[float] = []

        fasta_text = fasta_files[0].read_text()
        current_score: float | None = None
        for line in fasta_text.splitlines():
            line = line.strip()
            if line.startswith(">"):
                m = re.search(r"score=([\d.eE+\-]+)", line)
                current_score = float(m.group(1)) if m else None
                # Skip the wild-type header (sample=0 or score=nan)
                if "sample=0" in line:
                    current_score = None
            elif line and current_score is not None:
                sequences.append(line)
                scores.append(current_score)
                current_score = None

        if not sequences:
            raise HTTPException(status_code=500, detail="Could not parse any sequences from FASTA")

        return {"sequences": sequences, "scores": scores}


@app.get("/health")
async def health():
    return {"status": "ok", "repo": str(_REPO), "script_found": _SCRIPT.exists()}
