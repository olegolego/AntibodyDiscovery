#!/usr/bin/env python3
"""ESM2 embedding — VH/VL pairs, batched.

Input:
  sequences: list of {vh, vl?}          — batch mode
  vh: str                                — single-pair shorthand
  vl: str                                — single-pair shorthand (optional)
  model_size: "8M"|"35M"|"150M"|"650M"  — default 650M
  pool_mode: "mean"|"cls"|"per_residue" — default mean

Output (standard embedding format):
  n: int
  results: [{vh, vl, emb_vh, emb_vl}, ...]
  metadata: {model, model_size, pool_mode, dim}
"""
import json
import sys

_ALLOWED_AA = set("ACDEFGHIKLMNPQRSTVWY")

_MODEL_MAP = {
    "8M":   "facebook/esm2_t6_8M_UR50D",
    "35M":  "facebook/esm2_t12_35M_UR50D",
    "150M": "facebook/esm2_t30_150M_UR50D",
    "650M": "facebook/esm2_t33_650M_UR50D",
}
_POOL_MODES = {"mean", "cls", "per_residue"}


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    seq = "".join(lines).replace(" ", "").upper()
    return "".join(c if c in _ALLOWED_AA else "A" for c in seq)


def _embed(tokenizer, model, seq: str, pool_mode: str):
    import torch
    tokenized = tokenizer(seq, return_tensors="pt")
    with torch.no_grad():
        out = model(**tokenized)
    hidden = out.last_hidden_state        # (1, L+2, dim)
    residues = hidden[0, 1:-1, :]        # (L, dim)
    if pool_mode == "mean":
        return residues.mean(dim=0).numpy().tolist()
    elif pool_mode == "cls":
        return hidden[0, 0, :].numpy().tolist()
    else:  # per_residue
        return residues.numpy().tolist()


def _run(inputs: dict) -> dict:
    import torch
    from transformers import EsmModel, EsmTokenizer

    model_size = str(inputs.get("model_size", "650M")).strip()
    pool_mode  = str(inputs.get("pool_mode",  "mean")).strip().lower()

    if model_size not in _MODEL_MAP:
        raise ValueError(f"model_size must be one of {sorted(_MODEL_MAP)}")
    if pool_mode not in _POOL_MODES:
        raise ValueError(f"pool_mode must be one of {sorted(_POOL_MODES)}")

    # Normalize to list of (vh, vl|None) pairs
    seqs_raw = inputs.get("sequences")
    if seqs_raw is None:
        vh_raw = str(inputs.get("vh") or inputs.get("sequence") or "").strip()
        vl_raw = str(inputs.get("vl") or "").strip()
        seqs_raw = [{"vh": vh_raw, "vl": vl_raw or None}]
    elif isinstance(seqs_raw, dict):
        seqs_raw = [seqs_raw]

    pairs: list[tuple[str, str | None]] = []
    variant_extras: list[dict] = []   # extra per-variant fields to carry forward
    for entry in seqs_raw:
        vh = _clean(str(entry.get("vh") or ""))
        vl_str = str(entry.get("vl") or "").strip()
        vl = _clean(vl_str) if vl_str else None
        if not vh:
            raise ValueError("Each entry must have a non-empty 'vh'")
        pairs.append((vh, vl))
        variant_extras.append({k: v for k, v in entry.items() if k not in ("vh", "vl")})

    n = len(pairs)
    model_name = _MODEL_MAP[model_size]
    _progress(f"Loading {model_name}…")
    tokenizer = EsmTokenizer.from_pretrained(model_name)
    model = EsmModel.from_pretrained(model_name)
    model.eval()

    results = []
    for i, (vh, vl) in enumerate(pairs, 1):
        _progress(f"[{i}/{n}] VH len={len(vh)}" + (f" VL len={len(vl)}" if vl else ""))
        emb_vh = _embed(tokenizer, model, vh, pool_mode)
        emb_vl = _embed(tokenizer, model, vl, pool_mode) if vl else None
        # Preserve extra fields from the incoming variant (scores, etc.)
        results.append({**variant_extras[i - 1], "vh": vh, "vl": vl,
                        "emb_vh": emb_vh, "emb_vl": emb_vl})

    dim = model.config.hidden_size
    _progress(f"ESM2 done — {n} pair(s), dim={dim}")

    return {
        "n": n,
        "results": results,
        # Standard batch token — same variants with embeddings attached per-variant
        "sequences": {"n": n, "variants": results},
        "metadata": {
            "model": model_name,
            "model_size": model_size,
            "pool_mode": pool_mode,
            "dim": dim,
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
