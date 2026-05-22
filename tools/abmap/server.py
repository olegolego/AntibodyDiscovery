import os
import shutil
from pathlib import Path
from typing import Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/xdg-cache")

for cache_dir in (Path(os.environ["MPLCONFIGDIR"]), Path(os.environ["XDG_CACHE_HOME"])):
    cache_dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AbMAP Tool")

_ALLOWED_AA = set("ACDEFGHIKLMNPQRSTVWY")
_ABMAP_HOME = Path(os.getenv("ABMAP_HOME", "/opt/abmap"))
_PRETRAINED_DIR = _ABMAP_HOME / "pretrained_models"
_DSCRIPT_WEIGHTS = Path(os.getenv("DSCRIPT_LM_V1_PATH", "/opt/models/dscript_lm_v1.pt"))

_FOUNDATION_MODELS_LOADED: set[str] = set()
_ABMAP_MODELS: dict[tuple[str, str], "AbMAPAttn"] = {}


class EmbedRequest(BaseModel):
    sequence: str
    chain_type: str = "H"
    task: str = "structure"
    embedding_type: str = "fixed"
    num_mutations: int = 10


class PairEntry(BaseModel):
    vh: str
    vl: Optional[str] = None


class EmbedPairsRequest(BaseModel):
    sequences: list[PairEntry]
    task: str = "structure"
    embedding_type: str = "fixed"
    num_mutations: int = 10


def _clean_sequence(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if not line.startswith(">")]
    sequence = "".join(lines).replace(" ", "").upper()
    invalid = sorted(set(sequence) - _ALLOWED_AA)
    if invalid:
        raise ValueError(f"Sequence contains non-amino-acid characters: {invalid}")
    if not sequence:
        raise ValueError("sequence is required")
    return sequence


def _ensure_dscript_weights() -> None:
    if not _DSCRIPT_WEIGHTS.exists():
        return
    from dscript.pretrained import get_state_dict_path
    destination = Path(get_state_dict_path("lm_v1"))
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_DSCRIPT_WEIGHTS, destination)


def _load_foundation_model(plm_name: str) -> None:
    if plm_name in _FOUNDATION_MODELS_LOADED:
        return
    _ensure_dscript_weights()
    from abmap.plm_embed import reload_models_to_device
    reload_models_to_device(-1, plm_name)
    _FOUNDATION_MODELS_LOADED.add(plm_name)


def _checkpoint_path(chain_type: str, plm_name: str) -> Path:
    checkpoint = _PRETRAINED_DIR / f"AbMAP_{plm_name}_{chain_type}.pt"
    if not checkpoint.exists():
        raise FileNotFoundError(f"AbMAP checkpoint not found: {checkpoint}")
    return checkpoint


def _create_model(plm_name: str) -> "AbMAPAttn":
    from abmap.model import AbMAPAttn
    if plm_name != "beplerberger":
        raise ValueError(f"Unsupported PLM: {plm_name}")
    return AbMAPAttn(
        embed_dim=2200, mid_dim2=1024, mid_dim3=512,
        proj_dim=252, num_enc_layers=1, num_heads=16,
    ).to("cpu")


def _load_abmap_model(chain_type: str, plm_name: str = "beplerberger") -> "AbMAPAttn":
    key = (chain_type, plm_name)
    if key in _ABMAP_MODELS:
        return _ABMAP_MODELS[key]
    model = _create_model(plm_name)
    checkpoint = torch.load(_checkpoint_path(chain_type, plm_name), map_location="cpu")
    state_dict = checkpoint.get("model_state_dict", checkpoint)
    model.load_state_dict(state_dict)
    model.eval()
    _ABMAP_MODELS[key] = model
    return model


def _embed_sequence(
    sequence: str,
    chain_type: str,
    task: str,
    embedding_type: str,
    num_mutations: int,
    plm_name: str = "beplerberger",
) -> list:
    """Embed a single cleaned sequence. Returns float list."""
    from abmap.abmap_augment import ProteinEmbedding

    _load_foundation_model(plm_name)
    protein = ProteinEmbedding(sequence, chain_type, embed_device="cpu")
    try:
        cdr_embedding = protein.create_cdr_specific_embedding(
            plm_name, k=num_mutations, mask=True,
        )
    except ValueError:
        raise ValueError(
            f"AbMAP could not identify CDR regions (len={len(sequence)}). "
            "Sequence must be a complete VH or VL domain (110-130 AA) with all CDR loops."
        )

    model = _load_abmap_model(chain_type, plm_name)
    with torch.no_grad():
        embedding = model.embed(
            cdr_embedding.unsqueeze(0),
            task=task,
            embed_type=embedding_type,
        ).cpu()

    if embedding.dim() >= 2:
        embedding = embedding.squeeze(0)
    return embedding.tolist()


@app.post("/embed_pairs")
async def embed_pairs(req: EmbedPairsRequest):
    """Standard batch endpoint — returns {n, results: [{vh, vl, emb_vh, emb_vl}]}."""
    try:
        task           = req.task.strip().lower()
        embedding_type = req.embedding_type.strip().lower()
        if task not in {"structure", "function"}:
            raise ValueError("task must be 'structure' or 'function'")
        if embedding_type not in {"fixed", "variable"}:
            raise ValueError("embedding_type must be 'fixed' or 'variable'")
        if req.num_mutations < 1:
            raise ValueError("num_mutations must be at least 1")

        results = []
        for entry in req.sequences:
            vh = _clean_sequence(entry.vh)
            emb_vh = _embed_sequence(vh, "H", task, embedding_type, req.num_mutations)

            emb_vl = None
            vl = None
            if entry.vl and entry.vl.strip():
                vl = _clean_sequence(entry.vl)
                emb_vl = _embed_sequence(vl, "L", task, embedding_type, req.num_mutations)

            results.append({"vh": vh, "vl": vl, "emb_vh": emb_vh, "emb_vl": emb_vl})

        return {
            "n": len(results),
            "results": results,
            "metadata": {
                "task": task,
                "embedding_type": embedding_type,
                "num_mutations": req.num_mutations,
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AbMAP embedding failed: {exc}") from exc


@app.post("/embed")
async def embed(req: EmbedRequest):
    """Single-sequence endpoint — preserved for backward compatibility."""
    try:
        chain_type     = req.chain_type.upper().strip()
        task           = req.task.strip().lower()
        embedding_type = req.embedding_type.strip().lower()

        if chain_type not in {"H", "L"}:
            raise ValueError("chain_type must be 'H' or 'L'")
        if task not in {"structure", "function"}:
            raise ValueError("task must be 'structure' or 'function'")
        if embedding_type not in {"fixed", "variable"}:
            raise ValueError("embedding_type must be 'fixed' or 'variable'")
        if req.num_mutations < 1:
            raise ValueError("num_mutations must be at least 1")

        sequence = _clean_sequence(req.sequence)
        emb = _embed_sequence(sequence, chain_type, task, embedding_type, req.num_mutations)

        return {
            "embedding": emb,
            "metadata": {
                "chain_type": chain_type,
                "task": task,
                "embedding_type": embedding_type,
                "sequence_length": len(sequence),
                "embedding_shape": [len(emb)],
                "num_mutations": req.num_mutations,
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"AbMAP embedding failed: {exc}") from exc


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "abmap_home": str(_ABMAP_HOME),
        "checkpoint_dir": str(_PRETRAINED_DIR),
        "foundation_models_loaded": sorted(_FOUNDATION_MODELS_LOADED),
        "loaded_abmap_models": [f"{chain}:{plm}" for chain, plm in _ABMAP_MODELS.keys()],
    }
