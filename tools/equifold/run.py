#!/usr/bin/env python3
"""EquiFold subprocess entry point. Reads JSON from stdin, writes JSON to stdout."""
import json
import sys
import os
from pathlib import Path

# CRITICAL: chdir to repo root before any imports so cg_X0.npz is found via relative path
TOOL_DIR = Path(__file__).parent
REPO_DIR = TOOL_DIR / "repo"
os.chdir(str(REPO_DIR))
sys.path.insert(0, str(REPO_DIR))


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _clean_sequence(raw: str) -> str:
    lines = [l.strip() for l in str(raw).splitlines() if not l.startswith(">")]
    return "".join(lines).upper().replace(" ", "")


def _run(inputs: dict) -> dict:
    import torch
    import numpy as np
    from torch_geometric.data import Data
    from torch.utils.data import DataLoader
    from utils_data import MAX_DIST, cg_X0, collate_fn, x_to_pdb, sequence_to_feats
    import json as _json
    from models import NN

    heavy = _clean_sequence(inputs.get("heavy_chain", ""))
    light = _clean_sequence(inputs.get("light_chain", "") or "")

    if not heavy:
        raise ValueError("heavy_chain is required")
    if len(heavy) < 50:
        raise ValueError(f"Heavy chain is only {len(heavy)} AA — needs a full variable domain")

    if cg_X0 is None:
        raise RuntimeError("cg_X0.npz not loaded — did setup.sh run from the repo directory?")

    # Always use the "ab" model (handles VH-only by setting light to None)
    model_dir = REPO_DIR / "models"
    config_path = model_dir / "ab_config.json"
    weights_path = model_dir / "ab_weights.pt"
    if not weights_path.exists():
        raise FileNotFoundError(
            f"Model weights not found: {weights_path}\nRun tools/equifold/setup.sh first."
        )

    # Force CPU — e3nn JIT compilation is not tested on MPS
    device = torch.device("cpu")
    _progress(f"Device: cpu | H={len(heavy)} AA" + (f", L={len(light)} AA" if light else " (VH only)"))

    _progress("Loading EquiFold model weights…")
    with open(config_path) as f:
        config = _json.load(f)
    model = NN(**config)
    model.load_state_dict(torch.load(str(weights_path), map_location=device, weights_only=False))
    model = model.to(device)
    model.eval()

    _progress("Preparing coarse-grained features…")
    seq1 = heavy
    seq2 = light if light else None

    cg_cgidx, cg_resnum, scatter_index, scatter_w, dst_resnum, dst_atom, dst_resname, offset = \
        sequence_to_feats(seq1, dst_idx_offset=0)

    if seq2 is not None:
        cg_cgidx2, cg_resnum2, scatter_index2, scatter_w2, dst_resnum2, dst_atom2, dst_resname2, _ = \
            sequence_to_feats(seq2, dst_idx_offset=offset)
        seq2_offset = len(seq1) + MAX_DIST
        cg_cgidx    = np.concatenate([cg_cgidx,    cg_cgidx2])
        cg_resnum   = np.concatenate([cg_resnum,   cg_resnum2 + seq2_offset])
        scatter_index = np.concatenate([scatter_index, scatter_index2])
        scatter_w   = np.concatenate([scatter_w,   scatter_w2])
        dst_resnum  = np.concatenate([dst_resnum,  dst_resnum2 + seq2_offset])
        dst_atom    = np.concatenate([dst_atom,    dst_atom2])
        dst_resname = np.concatenate([dst_resname, dst_resname2])

    dtype = torch.float32
    cg_cgidx_t = torch.from_numpy(cg_cgidx)
    data = Data(
        num_nodes=len(cg_cgidx_t),
        cg_resnum=torch.from_numpy(cg_resnum),
        cg_cgidx=cg_cgidx_t,
        cg_X0=cg_X0[cg_cgidx_t].type(dtype),
        scatter_index=torch.from_numpy(scatter_index),
        scatter_w=torch.from_numpy(scatter_w).type(dtype),
        dst_resnum=torch.from_numpy(dst_resnum),
        dst_atom=dst_atom,
        dst_resname=dst_resname,
        uid="pred",
    )

    loader = DataLoader(
        [data], batch_size=1, drop_last=False, shuffle=False,
        num_workers=0, collate_fn=collate_fn, pin_memory=False,
    )

    _progress("Running EquiFold inference…")
    pdb_text = None
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(device)
            results_dict = model(
                batch, compute_loss=False, return_struct=True, set_RT_to_ground_truth=False
            )
            x_pred = results_dict["x_pred"][0][-1].cpu()
            item = batch[0]
            pdb_text = x_to_pdb(
                x_pred,
                item["dst_resnum"].cpu().numpy(),
                item["dst_resname"],   # numpy unicode array
                item["dst_atom"],      # numpy unicode array
            )

    if pdb_text is None:
        raise RuntimeError("EquiFold returned no structure")

    _progress("Done.")
    return {
        "structure": pdb_text,
        "metadata": {
            "heavy_length": len(heavy),
            "light_length": len(light) if light else 0,
            "model_type": "ab",
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
