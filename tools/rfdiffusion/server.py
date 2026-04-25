"""RFdiffusion HTTP wrapper."""
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="RFdiffusion Tool")


class DesignRequest(BaseModel):
    target_pdb: str | None = None   # PDB file content as string
    num_designs: int = 10
    num_residues: int = 80


@app.post("/design")
async def design(req: DesignRequest):
    from rfdiffusion.inference.utils import process_target  # type: ignore
    # RFdiffusion is invoked via its run_inference script; wrap as needed.
    raise HTTPException(status_code=501, detail="RFdiffusion adapter not fully implemented")


@app.get("/health")
async def health():
    return {"status": "ok"}
