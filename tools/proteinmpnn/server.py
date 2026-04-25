"""ProteinMPNN HTTP wrapper."""
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ProteinMPNN Tool")

_model = None


@app.on_event("startup")
async def load_model():
    global _model
    import protein_mpnn  # type: ignore
    _model = protein_mpnn.load_model()


class DesignRequest(BaseModel):
    structure: str       # PDB file content as string
    num_sequences: int = 8
    sampling_temp: float = 0.1


@app.post("/design")
async def design(req: DesignRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    with tempfile.NamedTemporaryFile(suffix=".pdb", mode="w", delete=False) as f:
        f.write(req.structure)
        pdb_path = f.name

    # Real invocation depends on ProteinMPNN's Python API or CLI wrapper.
    raise HTTPException(status_code=501, detail="ProteinMPNN adapter not fully implemented")


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _model is not None}
