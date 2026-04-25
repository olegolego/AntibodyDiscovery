"""ESMFold HTTP wrapper. Loads the model once at startup, serves predictions."""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="ESMFold Tool")

_model = None


@app.on_event("startup")
async def load_model():
    global _model
    import esm  # fair-esm package
    _model, _alphabet = esm.pretrained.esmfold_v1()
    _model = _model.eval().cuda()


class PredictRequest(BaseModel):
    sequence: str


@app.post("/predict")
async def predict(req: PredictRequest):
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")

    import torch
    with torch.no_grad():
        output = _model.infer_pdb(req.sequence)

    # output is a PDB string
    plddt = None  # optionally parse from output
    return {"pdb": output, "plddt": plddt}


@app.get("/health")
async def health():
    return {"status": "ok", "model_loaded": _model is not None}
