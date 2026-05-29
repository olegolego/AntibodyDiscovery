#!/usr/bin/env python3
"""One-hot amino acid embedding.

Canonical 20 AAs, alphabetical order (A C D E F G H I K L M N P Q R S T V W Y).
Non-standard residues → all-zero vector.

Input (stdin, JSON):
  heavy_chain / light_chain / sequence / sequences
  pool_mode: "mean" | "sum" | "per_residue"    — default "mean"

Output (stdout, JSON):
  n, results [{vh, vl, emb_vh, emb_vl}],
  embedding (first emb_vh), candidate_embeddings {seq: emb_vh}, metadata
"""
import json
import sys

_AA_ORDER = "ACDEFGHIKLMNPQRSTVWY"   # 20 canonical, alphabetical
_AA_IDX   = {aa: i for i, aa in enumerate(_AA_ORDER)}
N_DIM     = 20


def _clean(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    return "".join(lines).replace(" ", "").upper()


def _embed_seq(seq: str, pool_mode: str):
    import numpy as np
    mat = np.zeros((len(seq), N_DIM), dtype=float)
    for i, aa in enumerate(seq):
        j = _AA_IDX.get(aa)
        if j is not None:
            mat[i, j] = 1.0
    if not len(mat):
        return [0.0] * N_DIM
    if pool_mode == "sum":
        return mat.sum(axis=0).tolist()
    elif pool_mode == "per_residue":
        return mat.tolist()
    else:  # mean — gives AA composition
        return mat.mean(axis=0).tolist()


def _parse_sequences(inputs: dict) -> list[dict]:
    seqs_raw = inputs.get("sequences")
    if seqs_raw is not None:
        if isinstance(seqs_raw, dict) and "variants" in seqs_raw:
            seqs_raw = seqs_raw["variants"]
        elif isinstance(seqs_raw, dict):
            seqs_raw = [seqs_raw]
        if isinstance(seqs_raw, list) and seqs_raw:
            result = []
            for entry in seqs_raw:
                if isinstance(entry, str):
                    result.append({"vh": _clean(entry), "vl": None})
                else:
                    vh = _clean(str(entry.get("vh") or ""))
                    vl_raw = str(entry.get("vl") or "").strip()
                    result.append({"vh": vh, "vl": _clean(vl_raw) if vl_raw else None})
            return [e for e in result if e["vh"]]

    vh_raw = inputs.get("sequence") or inputs.get("heavy_chain") or inputs.get("vh") or ""
    if isinstance(vh_raw, list):
        return [{"vh": _clean(str(s)), "vl": None} for s in vh_raw if s]
    vl_raw = str(inputs.get("light_chain") or inputs.get("vl") or "").strip()
    vh = _clean(str(vh_raw).strip())
    vl = _clean(vl_raw) if vl_raw else None
    if not vh:
        raise ValueError("Provide 'heavy_chain', 'sequence', or 'sequences'.")
    return [{"vh": vh, "vl": vl}]


def _run(inputs: dict) -> dict:
    pool_mode = str(inputs.get("pool_mode", "mean")).strip().lower()
    if pool_mode not in ("mean", "sum", "per_residue"):
        pool_mode = "mean"

    sequences = _parse_sequences(inputs)
    results = []
    for pair in sequences:
        emb_vh = _embed_seq(pair["vh"], pool_mode)
        emb_vl = _embed_seq(pair["vl"], pool_mode) if pair["vl"] else None
        results.append({"vh": pair["vh"], "vl": pair["vl"], "emb_vh": emb_vh, "emb_vl": emb_vl})

    n = len(results)
    dim = N_DIM if pool_mode != "per_residue" else f"{N_DIM} per residue"

    return {
        "n": n,
        "results": results,
        "embedding": results[0]["emb_vh"] if results else None,
        "candidate_embeddings": {r["vh"]: r["emb_vh"] for r in results},
        "sequences": {"n": n, "variants": results},
        "metadata": {
            "pool_mode": pool_mode,
            "dim": dim,
            "aa_order": _AA_ORDER,
        },
    }


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        out = _run(inputs)
    except Exception as exc:
        import traceback
        json.dump({"error": str(exc), "traceback": traceback.format_exc()}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(out, sys.stdout)
    sys.stdout.flush()
