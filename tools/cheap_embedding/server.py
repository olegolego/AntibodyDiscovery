"""CHEAP protein embedding HTTP server.

Uses the CHEAP Pipeline (github.com/amyxlu/cheap-proteins).
The Pipeline loads Meta's ESMFold backbone (ESM2-3B + folding trunk, ~8 GB on CPU)
plus a trained hourglass compression autoencoder on top.

MEMORY NOTE: First request loads ~8 GB of model weights (ESMFold 3B). Requires
16+ GB free RAM. On machines with less free memory, increase swap or reduce
concurrent services before starting this server.

First request per (shorten_factor, dim) pair loads the checkpoint (~1 GB) plus
the shared ESMFold backbone (~8 GB). Subsequent requests reuse loaded models.
"""
import os
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Override CHEAP checkpoint cache dir if set
_CHEAP_CACHE = os.getenv("CHEAP_CACHE", os.path.expanduser("~/.cache/cheap"))
os.environ.setdefault("CHEAP_CACHE", _CHEAP_CACHE)

app = FastAPI(title="CHEAP Embedding")

# (shorten_factor, dim) → loaded Pipeline object
_pipelines: dict[tuple[int, int], object] = {}

_VALID_SHORTEN = {1, 2}
_VALID_DIMS    = {4, 8, 16, 32, 64, 128, 256, 512, 1024}


def _load_pipeline(shorten_factor: int, dim: int):
    key = (shorten_factor, dim)
    if key in _pipelines:
        return _pipelines[key]

    print(f"Loading CHEAP shorten={shorten_factor} dim={dim} "
          f"(checkpoint cache: {_CHEAP_CACHE})…", flush=True)

    from cheap import pretrained as _pretrained
    fn_name = f"CHEAP_shorten_{shorten_factor}_dim_{dim}"
    fn = getattr(_pretrained, fn_name, None)
    if fn is None:
        raise ValueError(
            f"No CHEAP model for shorten_factor={shorten_factor}, dim={dim}. "
            f"Available: CHEAP_shorten_{{1,2}}_dim_{{4,8,16,32,64,128,256,512,1024}}"
        )

    # load_pretrained_model returns the hourglass model only (no ESMFold backbone)
    model = fn(return_pipeline=False, model_dir=_CHEAP_CACHE, infer_mode=True)
    # get_pipeline loads ESMFold backbone (~8 GB) and wraps both; force CPU
    pipeline = _pretrained.get_pipeline(model, device="cpu")
    _pipelines[key] = pipeline
    print(f"✓ CHEAP shorten={shorten_factor} dim={dim} ready.", flush=True)
    return pipeline


class EmbedRequest(BaseModel):
    sequence: str
    shorten_factor: int = 1
    dim: int = 64


@app.post("/embed")
async def embed(req: EmbedRequest):
    seq = req.sequence.strip().upper()
    if not seq:
        raise HTTPException(status_code=400, detail="sequence is required")

    if req.shorten_factor not in _VALID_SHORTEN:
        raise HTTPException(status_code=400,
                            detail=f"shorten_factor must be 1 or 2, got {req.shorten_factor}")
    if req.dim not in _VALID_DIMS:
        raise HTTPException(status_code=400,
                            detail=f"dim must be one of {sorted(_VALID_DIMS)}, got {req.dim}")

    try:
        pipeline = _load_pipeline(req.shorten_factor, req.dim)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Model load failed: {exc}")

    try:
        with torch.no_grad():
            emb, mask = pipeline([seq])
        # emb:  (1, compressed_len, dim)
        # mask: (1, compressed_len)  — 1 for valid positions, 0 for padding
        emb_np  = emb[0].cpu().float().numpy()    # (C, dim)
        mask_np = mask[0].cpu().float().numpy()   # (C,)

        # Mean-pool over valid (non-padded) positions → (dim,)
        valid = emb_np[mask_np > 0.5]
        mean_vec = valid.mean(axis=0).tolist() if len(valid) > 0 else [0.0] * req.dim

        return {
            "embedding":         mean_vec,
            "residue_embeddings": emb_np.tolist(),
            "metadata": {
                "shorten_factor":   req.shorten_factor,
                "dim":              req.dim,
                "sequence_length":  len(seq),
                "compressed_length": int(mask_np.sum()),
                "output_shape":     list(emb_np.shape),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "loaded_models": [
            {"shorten_factor": sf, "dim": d}
            for sf, d in sorted(_pipelines)
        ],
    }
