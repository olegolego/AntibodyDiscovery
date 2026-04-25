"""AlphaFold HTTP wrapper. Wraps the ColabFold/LocalColabFold stack."""
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="AlphaFold Tool")


class PredictRequest(BaseModel):
    sequence: str
    num_recycles: int = 3


@app.post("/predict")
async def predict(req: PredictRequest):
    with tempfile.TemporaryDirectory() as tmpdir:
        fasta_path = Path(tmpdir) / "input.fasta"
        fasta_path.write_text(f">query\n{req.sequence}\n")

        result = subprocess.run(
            [
                "colabfold_batch",
                str(fasta_path),
                tmpdir,
                "--num-recycle", str(req.num_recycles),
                "--model-type", "alphafold2_ptm",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=result.stderr)

        pdb_files = list(Path(tmpdir).glob("*unrelaxed*.pdb"))
        if not pdb_files:
            raise HTTPException(status_code=500, detail="No PDB output produced")

        pdb_content = pdb_files[0].read_text()

    return {"pdb": pdb_content, "plddt": None}


@app.get("/health")
async def health():
    return {"status": "ok"}
