"""CHEAP protein embedding HTTP server.

Uses the CHEAP Pipeline (github.com/amyxlu/cheap-proteins).
First request loads ~8 GB of ESMFold weights on CPU.
"""
import os
import torch
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

_CHEAP_CACHE = os.getenv("CHEAP_CACHE", os.path.expanduser("~/.cache/cheap"))
os.environ.setdefault("CHEAP_CACHE", _CHEAP_CACHE)

app = FastAPI(title="CHEAP Embedding")

_pipelines: dict[tuple[int, int], object] = {}

_VALID_SHORTEN = {1, 2}
_VALID_DIMS    = {4, 8, 16, 32, 64, 128, 256, 512, 1024}


def _load_pipeline(shorten_factor: int, dim: int):
    key = (shorten_factor, dim)
    if key in _pipelines:
        return _pipelines[key]
    print(f"Loading CHEAP shorten={shorten_factor} dim={dim}…", flush=True)
    from cheap import pretrained as _pretrained
    fn_name = f"CHEAP_shorten_{shorten_factor}_dim_{dim}"
    fn = getattr(_pretrained, fn_name, None)
    if fn is None:
        raise ValueError(
            f"No CHEAP model for shorten_factor={shorten_factor}, dim={dim}."
        )
    model = fn(return_pipeline=False, model_dir=_CHEAP_CACHE, infer_mode=True)
    pipeline = _pretrained.get_pipeline(model, device="cpu")
    _pipelines[key] = pipeline
    print(f"CHEAP shorten={shorten_factor} dim={dim} ready.", flush=True)
    return pipeline


def _embed_sequence(pipeline, seq: str, dim: int) -> list:
    """Embed a single sequence. Returns mean-pooled float list."""
    import numpy as np
    with torch.no_grad():
        emb, mask = pipeline([seq])
    emb_np  = emb[0].cpu().float().numpy()   # (C, dim)
    mask_np = mask[0].cpu().float().numpy()  # (C,)
    valid = emb_np[mask_np > 0.5]
    return valid.mean(axis=0).tolist() if len(valid) > 0 else [0.0] * dim


class EmbedRequest(BaseModel):
    sequence: str
    shorten_factor: int = 1
    dim: int = 64


class PairEntry(BaseModel):
    vh: str
    vl: Optional[str] = None


class EmbedPairsRequest(BaseModel):
    sequences: list[PairEntry]
    shorten_factor: int = 1
    dim: int = 64


@app.post("/embed_pairs")
async def embed_pairs(req: EmbedPairsRequest):
    """Standard batch endpoint — returns {n, results: [{vh, vl, emb_vh, emb_vl}]}."""
    if req.shorten_factor not in _VALID_SHORTEN:
        raise HTTPException(status_code=400, detail=f"shorten_factor must be 1 or 2")
    if req.dim not in _VALID_DIMS:
        raise HTTPException(status_code=400, detail=f"dim must be one of {sorted(_VALID_DIMS)}")

    try:
        pipeline = _load_pipeline(req.shorten_factor, req.dim)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Model load failed: {exc}")

    try:
        results = []
        for entry in req.sequences:
            vh = entry.vh.strip().upper()
            if not vh:
                raise HTTPException(status_code=400, detail="vh is required in each entry")
            emb_vh = _embed_sequence(pipeline, vh, req.dim)

            emb_vl = None
            vl = None
            if entry.vl and entry.vl.strip():
                vl = entry.vl.strip().upper()
                emb_vl = _embed_sequence(pipeline, vl, req.dim)

            results.append({"vh": vh, "vl": vl, "emb_vh": emb_vh, "emb_vl": emb_vl})

        return {
            "n": len(results),
            "results": results,
            "metadata": {"shorten_factor": req.shorten_factor, "dim": req.dim},
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/embed")
async def embed(req: EmbedRequest):
    """Single-sequence endpoint — preserved for backward compatibility."""
    seq = req.sequence.strip().upper()
    if not seq:
        raise HTTPException(status_code=400, detail="sequence is required")
    if req.shorten_factor not in _VALID_SHORTEN:
        raise HTTPException(status_code=400, detail=f"shorten_factor must be 1 or 2")
    if req.dim not in _VALID_DIMS:
        raise HTTPException(status_code=400, detail=f"dim must be one of {sorted(_VALID_DIMS)}")

    try:
        pipeline = _load_pipeline(req.shorten_factor, req.dim)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Model load failed: {exc}")

    try:
        with torch.no_grad():
            emb, mask = pipeline([seq])
        emb_np  = emb[0].cpu().float().numpy()
        mask_np = mask[0].cpu().float().numpy()
        valid = emb_np[mask_np > 0.5]
        mean_vec = valid.mean(axis=0).tolist() if len(valid) > 0 else [0.0] * req.dim

        return {
            "embedding":          mean_vec,
            "residue_embeddings": emb_np.tolist(),
            "metadata": {
                "shorten_factor":    req.shorten_factor,
                "dim":               req.dim,
                "sequence_length":   len(seq),
                "compressed_length": int(mask_np.sum()),
                "output_shape":      list(emb_np.shape),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "loaded_models": [{"shorten_factor": sf, "dim": d} for sf, d in sorted(_pipelines)],
    }
