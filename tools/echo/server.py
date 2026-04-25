"""Minimal echo server for pipeline testing. No GPU, no special deps."""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

app = FastAPI(title="Echo Tool")


class InvokeRequest(BaseModel):
    inputs: dict[str, Any]


@app.post("/invoke")
async def invoke(req: InvokeRequest):
    return {"outputs": req.inputs}


@app.get("/health")
async def health():
    return {"status": "ok"}
