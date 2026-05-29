#!/usr/bin/env python3
"""19-dimensional physicochemical amino acid embedding.

Each residue is mapped to 19 biophysical properties (AAindex-based), then
z-score normalised across the 20 canonical AAs. Per-residue vectors are
pooled to a fixed embedding (mean / max / per_residue).

Input (stdin, JSON):
  heavy_chain / light_chain / sequence / sequences   — same convention as all other embedding tools
  pool_mode: "mean" | "max" | "per_residue"          — default "mean"

Output (stdout, JSON):
  n, results [{vh, vl, emb_vh, emb_vl}],
  embedding (first emb_vh), candidate_embeddings {seq: emb_vh}, metadata
"""
import json
import sys

_ALLOWED_AA = set("ACDEFGHIKLMNPQRSTVWY")

# ── Physicochemical property table ─────────────────────────────────────────────
# 20 canonical AAs, alphabetical order.
# 19 features per residue (columns):
#  0  Kyte-Doolittle hydrophobicity  (KYTJ820101)
#  1  Hopp-Woods hydrophilicity      (HOPT810101)
#  2  Eisenberg hydrophobicity       (EISD840101)
#  3  Molecular weight (Da)
#  4  Side-chain volume (Å³)         (Zamyatnin 1972)
#  5  Steric parameter               (Charton 1982, CHAM820101)
#  6  Polarizability (×10⁻²⁴ cm³)   (Charton 1982, CHAM820102)
#  7  Formal charge at pH 7
#  8  Isoelectric point (pI)
#  9  Alpha-helix propensity         (Chou-Fasman 1978)
# 10  Beta-sheet propensity          (Chou-Fasman 1978)
# 11  Turn propensity                (Chou-Fasman 1978)
# 12  Backbone flexibility           (Vihinen 1994, normalised B-factor)
# 13  Relative accessible surface area (Tien 2013)
# 14  Refractivity                   (Ohkubo 2007)
# 15  H-bond donors (side chain)
# 16  H-bond acceptors (side chain)
# 17  Aromaticity (0/1)
# 18  Side-chain carbon count

_RAW = {
    #  [0]    [1]    [2]     [3]     [4]  [5]   [6]  [7]   [8]  [9]   [10]  [11]  [12] [13]   [14]  [15][16][17][18]
    "A": [ 1.80, -0.50,  0.25,  89.09,  67, 0.52, 0.78,  0, 6.00, 1.45, 0.97, 0.77, 0.36, 0.29,  4.34, 0, 0, 0, 1],
    "C": [ 2.50, -1.00,  0.04, 121.16,  86, 0.56, 1.48,  0, 5.07, 0.77, 1.30, 0.81, 0.35, 0.19, 35.77, 1, 0, 0, 1],
    "D": [-3.50,  3.00, -0.72, 133.10,  91, 0.68, 0.90, -1, 2.77, 0.98, 0.80, 1.41, 0.51, 0.51, 12.00, 0, 2, 0, 2],
    "E": [-3.50,  3.00, -0.62, 147.13, 109, 0.68, 1.35, -1, 3.22, 1.53, 0.26, 0.99, 0.50, 0.52, 17.26, 0, 2, 0, 3],
    "F": [ 2.80, -2.50,  0.61, 165.19, 135, 0.70, 2.59,  0, 5.48, 1.12, 1.28, 0.59, 0.31, 0.29, 29.40, 0, 0, 1, 7],
    "G": [-0.40,  0.00,  0.16,  75.03,  48, 0.00, 0.00,  0, 5.97, 0.53, 0.81, 1.64, 0.54, 0.35,  0.00, 0, 0, 0, 0],
    "H": [-3.20, -0.50, -0.40, 155.16, 118, 0.70, 2.40,  0, 7.59, 1.24, 0.71, 0.68, 0.32, 0.47, 21.81, 2, 1, 1, 4],
    "I": [ 4.50, -1.80,  0.73, 131.17, 124, 0.76, 1.90,  0, 6.02, 1.00, 1.60, 0.51, 0.46, 0.23, 19.06, 0, 0, 0, 4],
    "K": [-3.90,  3.00, -1.10, 146.19, 135, 0.68, 1.89,  1, 9.74, 1.07, 0.74, 1.01, 0.47, 0.57, 21.29, 2, 0, 0, 4],
    "L": [ 3.80, -1.80,  0.53, 131.17, 124, 0.76, 2.30,  0, 5.98, 1.34, 1.22, 0.58, 0.37, 0.25, 21.46, 0, 0, 0, 4],
    "M": [ 1.90, -1.30,  0.26, 149.21, 124, 0.70, 2.62,  0, 5.74, 1.20, 1.67, 0.52, 0.30, 0.31, 26.43, 0, 1, 0, 3],
    "N": [-3.50,  0.20, -0.64, 132.12,  96, 0.68, 1.36,  0, 5.41, 0.73, 0.65, 1.28, 0.46, 0.46, 13.28, 2, 2, 0, 2],
    "P": [-1.60,  0.00, -0.07, 115.13,  90, 0.36, 1.22,  0, 6.30, 0.59, 0.62, 1.91, 0.51, 0.26, 10.93, 0, 0, 0, 3],
    "Q": [-3.50,  0.20, -0.69, 146.15, 114, 0.68, 1.81,  0, 5.65, 1.17, 1.23, 0.97, 0.49, 0.52, 17.56, 2, 2, 0, 3],
    "R": [-4.50,  3.00, -1.76, 174.20, 148, 0.68, 2.52,  1,10.76, 0.79, 0.90, 0.88, 0.53, 0.59, 26.66, 5, 0, 0, 4],
    "S": [-0.80,  0.30, -0.26, 105.09,  73, 0.35, 0.89,  0, 5.68, 0.79, 0.72, 1.43, 0.51, 0.40,  6.35, 1, 1, 0, 1],
    "T": [-0.70, -0.40, -0.18, 119.12,  93, 0.50, 1.24,  0, 5.60, 0.82, 1.20, 1.03, 0.44, 0.38, 11.01, 1, 1, 0, 2],
    "V": [ 4.20, -1.50,  0.54, 117.15, 105, 0.76, 1.46,  0, 5.96, 1.14, 1.65, 0.51, 0.39, 0.25, 13.92, 0, 0, 0, 3],
    "W": [-0.90, -3.40,  0.37, 204.23, 163, 0.70, 3.65,  0, 5.89, 1.14, 1.19, 0.75, 0.31, 0.39, 42.53, 1, 0, 1, 9],
    "Y": [-1.30, -2.30,  0.02, 181.19, 141, 0.70, 2.84,  0, 5.66, 0.61, 1.29, 1.05, 0.42, 0.42, 31.53, 1, 1, 1, 7],
}

_FEATURE_NAMES = [
    "kd_hydrophobicity", "hw_hydrophilicity", "eisenberg_hydrophobicity",
    "molecular_weight", "sc_volume", "steric_param", "polarizability",
    "formal_charge", "pI", "helix_propensity", "sheet_propensity", "turn_propensity",
    "flexibility", "rel_asa", "refractivity",
    "hbond_donors", "hbond_acceptors", "aromaticity", "sc_carbons",
]
N_FEATURES = 19


def _build_lookup():
    import numpy as np
    aas = sorted(_RAW.keys())
    mat = np.array([_RAW[aa] for aa in aas], dtype=float)   # (20, 19)
    mu  = mat.mean(axis=0)
    sd  = mat.std(axis=0)
    sd[sd < 1e-9] = 1.0   # avoid div-by-zero for constant features (aromaticity has real variance)
    normed = (mat - mu) / sd
    return {aa: normed[i].tolist() for i, aa in enumerate(aas)}, mu.tolist(), sd.tolist()


_LOOKUP, _MU, _SD = _build_lookup()
_UNK = [0.0] * N_FEATURES   # unknown / non-standard AA → zero vector


def _clean(raw: str) -> str:
    lines = [l.strip() for l in raw.splitlines() if not l.startswith(">")]
    seq = "".join(lines).replace(" ", "").upper()
    return seq


def _embed_seq(seq: str, pool_mode: str):
    """Return embedding for one sequence string."""
    import numpy as np
    residues = np.array([_LOOKUP.get(aa, _UNK) for aa in seq], dtype=float)  # (L, 19)
    if not len(residues):
        return [0.0] * N_FEATURES
    if pool_mode == "mean":
        return residues.mean(axis=0).tolist()
    elif pool_mode == "max":
        return residues.max(axis=0).tolist()
    else:  # per_residue
        return residues.tolist()


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
    if pool_mode not in ("mean", "max", "per_residue"):
        pool_mode = "mean"

    sequences = _parse_sequences(inputs)
    results = []
    for pair in sequences:
        emb_vh = _embed_seq(pair["vh"], pool_mode)
        emb_vl = _embed_seq(pair["vl"], pool_mode) if pair["vl"] else None
        results.append({"vh": pair["vh"], "vl": pair["vl"], "emb_vh": emb_vh, "emb_vl": emb_vl})

    n = len(results)
    dim = N_FEATURES if pool_mode != "per_residue" else f"{N_FEATURES} per residue"

    return {
        "n": n,
        "results": results,
        "metadata": {
            "pool_mode": pool_mode,
            "dim": dim,
            "n_features": N_FEATURES,
            "feature_names": _FEATURE_NAMES,
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
