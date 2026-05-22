#!/usr/bin/env python3
"""AbLang embedding — VH/VL pairs, batched.

Input:
  sequences: list of {vh, vl?, ...extra}          — batch mode
             OR standard batch token {n, variants: [{vh, vl, ...extra}, ...]}
  vh: str                                          — single-pair shorthand
  vl: str                                          — single-pair shorthand (optional)
  mode: "seqcoding" | "rescoding"                  — default seqcoding

Output (standard embedding format):
  n: int
  results: [{vh, vl, emb_vh, emb_vl, ...extra}, ...]
  sequences: {n, variants: results}  — standard batch token with embeddings attached
  metadata: {model, dim, mode}
"""
import json
import sys

_ALLOWED_AA = set("ACDEFGHIKLMNPQRSTVWY*")
_VALID_MODES = {"seqcoding", "rescoding"}


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    seq = "".join(lines).replace(" ", "").upper()
    invalid = sorted(set(seq) - _ALLOWED_AA)
    if invalid:
        raise ValueError(f"Unexpected characters in sequence: {invalid}")
    return seq


def _embed(model, seq: str, mode: str):
    import numpy as np
    result = model((seq,), mode=mode)
    arr = np.asarray(result).squeeze(0)
    return arr.tolist()


def _run(inputs: dict) -> dict:
    import ablang

    mode = str(inputs.get("mode", "seqcoding")).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(_VALID_MODES)}")

    # Normalize to list of variant dicts, preserving extra fields
    seqs_raw = inputs.get("sequences")
    if seqs_raw is None:
        vh_raw = str(inputs.get("vh") or inputs.get("sequence") or "").strip()
        vl_raw = str(inputs.get("vl") or "").strip()
        seqs_raw = [{"vh": vh_raw, "vl": vl_raw or None}]
    elif isinstance(seqs_raw, dict) and "variants" in seqs_raw:
        # Standard batch token {n, variants: [...]}
        seqs_raw = seqs_raw["variants"]
    elif isinstance(seqs_raw, dict):
        seqs_raw = [seqs_raw]

    pairs: list[tuple[str, str | None]] = []
    variant_extras: list[dict] = []
    for entry in seqs_raw:
        vh = _clean(str(entry.get("vh") or ""))
        vl_str = str(entry.get("vl") or "").strip()
        vl = _clean(vl_str) if vl_str else None
        if not vh:
            raise ValueError("Each entry must have a non-empty 'vh'")
        pairs.append((vh, vl))
        variant_extras.append({k: v for k, v in entry.items() if k not in ("vh", "vl")})

    n = len(pairs)
    has_vl = any(vl for _, vl in pairs)

    _progress(f"AbLang: loading heavy model (mode={mode})…")
    model_h = ablang.pretrained("heavy")
    model_h.freeze()

    model_l = None
    if has_vl:
        _progress("AbLang: loading light model…")
        model_l = ablang.pretrained("light")
        model_l.freeze()

    results = []
    for i, (vh, vl) in enumerate(pairs, 1):
        _progress(f"[{i}/{n}] VH len={len(vh)}" + (f" VL len={len(vl)}" if vl else ""))
        emb_vh = _embed(model_h, vh, mode)
        emb_vl = _embed(model_l, vl, mode) if (vl and model_l) else None
        # Preserve extra fields from the incoming variant (scores, etc.)
        results.append({**variant_extras[i - 1], "vh": vh, "vl": vl,
                        "emb_vh": emb_vh, "emb_vl": emb_vl})

    dim = len(results[0]["emb_vh"]) if results and mode == "seqcoding" else None
    _progress(f"AbLang done — {n} pair(s), dim={dim}")

    return {
        "n": n,
        "results": results,
        # Standard batch token — same variants with embeddings attached per-variant
        "sequences": {"n": n, "variants": results},
        "metadata": {"model": "ablang", "mode": mode, "dim": dim},
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
