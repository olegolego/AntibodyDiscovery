#!/usr/bin/env python3
"""ESM2 embedding subprocess entry point. Reads JSON from stdin, writes JSON to stdout.

Uses HuggingFace transformers EsmModel (NOT EsmForProteinFolding).
Weights are downloaded automatically to ~/.cache/huggingface on first run.
"""
import json
import sys

_ALLOWED_AA = set("ACDEFGHIKLMNPQRSTVWY")

_MODEL_MAP = {
    "8M":   "facebook/esm2_t6_8M_UR50D",      # 320-dim
    "35M":  "facebook/esm2_t12_35M_UR50D",     # 480-dim
    "150M": "facebook/esm2_t30_150M_UR50D",    # 640-dim
    "650M": "facebook/esm2_t33_650M_UR50D",    # 1280-dim
}

_POOL_MODES = {"mean", "cls", "per_residue"}


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean_sequence(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    seq = "".join(lines).replace(" ", "").upper()
    # Silently replace non-canonical AAs with Ala (same as AbLang)
    seq = "".join(c if c in _ALLOWED_AA else "A" for c in seq)
    if not seq:
        raise ValueError("sequence is required")
    return seq


def _run(inputs: dict) -> dict:
    import torch
    from transformers import EsmModel, EsmTokenizer

    sequence  = _clean_sequence(str(inputs.get("sequence", "")))
    model_size = str(inputs.get("model_size", "650M")).strip()
    pool_mode  = str(inputs.get("pool_mode",  "mean")).strip().lower()

    if model_size not in _MODEL_MAP:
        raise ValueError(f"model_size must be one of {sorted(_MODEL_MAP)}")
    if pool_mode not in _POOL_MODES:
        raise ValueError(f"pool_mode must be one of {sorted(_POOL_MODES)}")

    model_name = _MODEL_MAP[model_size]
    _progress(f"Loading {model_name} (downloads on first use)…")
    tokenizer = EsmTokenizer.from_pretrained(model_name)
    model = EsmModel.from_pretrained(model_name)
    model.eval()

    _progress(f"Encoding sequence (len={len(sequence)}, pool={pool_mode})…")
    tokenized = tokenizer(sequence, return_tensors="pt")
    with torch.no_grad():
        out = model(**tokenized)

    # last_hidden_state: (1, L+2, dim) — [CLS] at idx 0, [EOS] at idx -1
    hidden   = out.last_hidden_state          # (1, L+2, dim)
    residues = hidden[0, 1:-1, :]             # (L, dim) — strip special tokens
    dim      = hidden.shape[-1]

    embedding     = None
    res_embeddings = None

    if pool_mode == "mean":
        vec = residues.mean(dim=0)            # (dim,)
        embedding = vec.numpy().tolist()
        shape = [dim]
    elif pool_mode == "cls":
        vec = hidden[0, 0, :]                 # (dim,)
        embedding = vec.numpy().tolist()
        shape = [dim]
    else:  # per_residue
        arr = residues.numpy()                # (L, dim)
        res_embeddings = arr.tolist()
        shape = list(arr.shape)

    _progress(f"ESM2 done — model={model_size}, dim={dim}, shape={shape}")

    return {
        "embedding":     embedding,
        "res_embeddings": res_embeddings,
        "metadata": {
            "model":            model_name,
            "model_size":       model_size,
            "pool_mode":        pool_mode,
            "sequence_length":  len(sequence),
            "embedding_dim":    dim,
            "output_shape":     shape,
        },
    }


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
