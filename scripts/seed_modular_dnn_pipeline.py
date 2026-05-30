"""Seed the Modular DNN-MLDE pipeline into the database.

Each scoring objective gets its own custom_dnn node (user-designed architecture).
A compute node in loop_end runs UCB acquisition over candidate predictions from
all custom_dnn nodes, then selects the best next sequence.

Run: python scripts/seed_modular_dnn_pipeline.py
"""
from __future__ import annotations

import datetime
import json
import sqlite3
import sys
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "protein_design.db"
SOURCE_LOOP_ID = "b7fc778c-1567-48b2-81fd-01484866210a"

# Compact 3-layer MLP (input dim = 512 for AbMAP)
_ARCH_R1 = {
    "version": "1.0",
    "nodes": [
        {"id": "input_0",  "type": "Input",   "params": {"features": 512},                                    "position": {"x": 50,  "y": 200}},
        {"id": "linear_0", "type": "Linear",  "params": {"in_features": 512, "out_features": 128, "bias": True}, "position": {"x": 250, "y": 200}},
        {"id": "relu_0",   "type": "ReLU",    "params": {},                                                    "position": {"x": 430, "y": 200}},
        {"id": "drop_0",   "type": "Dropout", "params": {"p": 0.2},                                            "position": {"x": 580, "y": 200}},
        {"id": "linear_1", "type": "Linear",  "params": {"in_features": 128, "out_features": 32, "bias": True}, "position": {"x": 730, "y": 200}},
        {"id": "relu_1",   "type": "ReLU",    "params": {},                                                    "position": {"x": 900, "y": 200}},
        {"id": "output_0", "type": "Output",  "params": {"out_features": 1, "task": "regression"},             "position": {"x": 1050, "y": 200}},
    ],
    "edges": [
        {"id": "e0", "source": "input_0",  "target": "linear_0"},
        {"id": "e1", "source": "linear_0", "target": "relu_0"},
        {"id": "e2", "source": "relu_0",   "target": "drop_0"},
        {"id": "e3", "source": "drop_0",   "target": "linear_1"},
        {"id": "e4", "source": "linear_1", "target": "relu_1"},
        {"id": "e5", "source": "relu_1",   "target": "output_0"},
    ],
}

# Slightly wider architecture for rank-2
_ARCH_R2 = {
    "version": "1.0",
    "nodes": [
        {"id": "input_0",  "type": "Input",   "params": {"features": 512},                                    "position": {"x": 50,  "y": 200}},
        {"id": "linear_0", "type": "Linear",  "params": {"in_features": 512, "out_features": 256, "bias": True}, "position": {"x": 250, "y": 200}},
        {"id": "relu_0",   "type": "ReLU",    "params": {},                                                    "position": {"x": 430, "y": 200}},
        {"id": "drop_0",   "type": "Dropout", "params": {"p": 0.3},                                            "position": {"x": 580, "y": 200}},
        {"id": "linear_1", "type": "Linear",  "params": {"in_features": 256, "out_features": 64, "bias": True}, "position": {"x": 730, "y": 200}},
        {"id": "relu_1",   "type": "ReLU",    "params": {},                                                    "position": {"x": 900, "y": 200}},
        {"id": "output_0", "type": "Output",  "params": {"out_features": 1, "task": "regression"},             "position": {"x": 1050, "y": 200}},
    ],
    "edges": [
        {"id": "e0", "source": "input_0",  "target": "linear_0"},
        {"id": "e1", "source": "linear_0", "target": "relu_0"},
        {"id": "e2", "source": "relu_0",   "target": "drop_0"},
        {"id": "e3", "source": "drop_0",   "target": "linear_1"},
        {"id": "e4", "source": "linear_1", "target": "relu_1"},
        {"id": "e5", "source": "relu_1",   "target": "output_0"},
    ],
}

# Loop-end compute: UCB over candidate_predictions from N custom_dnn nodes.
# In compute nodes the executor injects ALL upstream outputs as {node_id}_{key} variables.
# So custom_dnn_r1.candidate_predictions → custom_dnn_r1_candidate_predictions, etc.
LOOP_END_CODE = """
import numpy as np

r1_preds = custom_dnn_r1_candidate_predictions or {}
r2_preds = custom_dnn_r2_candidate_predictions or {}

# Merge predictions from all available rank models
preds_all = {k: v for k, v in {"r1": r1_preds, "r2": r2_preds}.items() if v}

if not preds_all:
    result = {
        "next_heavy_chain": loop_start_heavy_chain,
        "next_light_chain": loop_start_light_chain,
        "n_candidates_scored": 0,
        "acquisition_scores": {},
    }
else:
    # Intersect sequences present in all rank models
    all_seqs_sets = [set(p.keys()) for p in preds_all.values()]
    seqs = list(all_seqs_sets[0].intersection(*all_seqs_sets[1:]) if len(all_seqs_sets) > 1 else all_seqs_sets[0])

    if not seqs:
        result = {
            "next_heavy_chain": loop_start_heavy_chain,
            "next_light_chain": loop_start_light_chain,
            "n_candidates_scored": 0,
            "acquisition_scores": {},
        }
    else:
        preds_list = list(preds_all.values())
        pred_matrix = np.array([[float(p.get(s, 0.0)) for s in seqs] for p in preds_list])
        mu    = pred_matrix.mean(axis=0)   # mean predicted score (lower = better)
        sigma = pred_matrix.std(axis=0)    # epistemic uncertainty across models

        kappa = 2.0
        # UCB-min: subtract uncertainty to encourage exploration of low-score regions
        acquisition = mu - kappa * sigma

        acq = {s: float(a) for s, a in zip(seqs, acquisition)}
        best_seq = min(acq, key=acq.get)

        result = {
            "next_heavy_chain": best_seq,
            "next_light_chain": loop_start_light_chain,
            "selected_ucb_score": acq[best_seq],
            "n_candidates_scored": len(seqs),
            "acquisition_scores": acq,
        }
"""


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))

    # ── Load source loop run for PDB + existing params ────────────────────────
    row = conn.execute(
        "SELECT pipeline_snapshot FROM loop_runs WHERE id=?", (SOURCE_LOOP_ID,)
    ).fetchone()
    if not row:
        print(f"ERROR: source loop {SOURCE_LOOP_ID} not found.", file=sys.stderr)
        sys.exit(1)

    snap: dict = json.loads(row[0])

    pdb_content = ""
    for node in snap["nodes"]:
        if node["id"] == "target_in":
            pdb_content = (node.get("params") or {}).get("pdb", "")
            break

    loop_start_params: dict = {}
    for node in snap["nodes"]:
        if node["id"] == "loop_start":
            loop_start_params = dict(node.get("params") or {})
            break
    loop_start_params["max_iterations"] = 3  # small test run

    haddock_residues = ""
    for node in snap["nodes"]:
        if node.get("tool") == "haddock3" or node["id"].startswith("haddock"):
            haddock_residues = (node.get("params") or {}).get("antigen_active_residues", "")
            if haddock_residues:
                break

    cdr_params: dict = {}
    for node in snap["nodes"]:
        if node.get("tool") == "cdr_mutator" or node["id"] == "cdr_mutator":
            cdr_params = node.get("params") or {}
            break

    # ── Build pipeline ─────────────────────────────────────────────────────────
    pipeline_id = "modular-dnn-" + str(uuid.uuid4())[:8]
    pipeline = {
        "id": pipeline_id,
        "name": "Modular DNN · UCB Active Learning (Loop)",
        "schema_version": "1",
        "nodes": [
            {
                "id": "loop_start",
                "tool": "loop_start",
                "params": loop_start_params,
                "position": {"x": 50, "y": 350},
            },
            {
                "id": "target_in",
                "tool": "target_input",
                "params": {"pdb": pdb_content},
                "position": {"x": 50, "y": 80},
            },
            {
                "id": "immunebuilder",
                "tool": "immunebuilder",
                "params": {},
                "position": {"x": 310, "y": 350},
            },
            {
                "id": "haddock_r1",
                "tool": "haddock3",
                "params": {
                    "antigen_active_residues": haddock_residues,
                    "rigid_sampling": 20,
                    "select_top": 5,
                },
                "position": {"x": 580, "y": 200},
            },
            {
                "id": "haddock_r2",
                "tool": "haddock3",
                "params": {
                    "antigen_active_residues": haddock_residues,
                    "rigid_sampling": 20,
                    "select_top": 5,
                },
                "position": {"x": 580, "y": 420},
            },
            # AbMAP embedding for the oracle sequence (training input)
            {
                "id": "abmap_train",
                "tool": "abmap",
                "params": {"chain_type": "H", "num_mutations": 10},
                "position": {"x": 310, "y": 150},
            },
            # Custom DNN for HADDOCK rank-1 score — trains on each new evaluation
            {
                "id": "custom_dnn_r1",
                "tool": "custom_dnn",
                "params": {
                    "architecture_spec": _ARCH_R1,
                    "task": "regression",
                    "epochs": 80,
                    "learning_rate": 0.001,
                    "score_key": "scores_rank_1",
                },
                "position": {"x": 860, "y": 200},
            },
            # Custom DNN for HADDOCK rank-2 score — different architecture
            {
                "id": "custom_dnn_r2",
                "tool": "custom_dnn",
                "params": {
                    "architecture_spec": _ARCH_R2,
                    "task": "regression",
                    "epochs": 80,
                    "learning_rate": 0.001,
                    "score_key": "scores_rank_2",
                },
                "position": {"x": 860, "y": 420},
            },
            # CDR mutator → candidate variants
            {
                "id": "cdr_mutator",
                "tool": "cdr_mutator",
                "params": cdr_params,
                "position": {"x": 310, "y": 560},
            },
            # AbMAP batch embedding for all CDR variants
            {
                "id": "abmap_cand",
                "tool": "abmap",
                "params": {"chain_type": "H", "num_mutations": 5},
                "position": {"x": 580, "y": 640},
            },
            # Loop end: UCB selection over both DNN predictions
            {
                "id": "loop_end",
                "tool": "loop_end",
                "params": {"code": LOOP_END_CODE.strip()},
                "position": {"x": 1140, "y": 380},
            },
        ],
        "edges": [
            # loop_start → immunebuilder
            {"source": "loop_start.heavy_chain", "target": "immunebuilder.heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "immunebuilder.light_chain"},
            # loop_start → abmap_train (single-seq embedding for training)
            {"source": "loop_start.heavy_chain", "target": "abmap_train.heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "abmap_train.light_chain"},
            # target → both HADDOCK runs
            {"source": "target_in.pdb", "target": "haddock_r1.antigen"},
            {"source": "target_in.pdb", "target": "haddock_r2.antigen"},
            # immunebuilder → haddock (structures 1 and 2)
            {"source": "immunebuilder.structure_1", "target": "haddock_r1.antibody"},
            {"source": "immunebuilder.structure_2", "target": "haddock_r2.antibody"},
            # abmap_train.embedding → both custom_dnn training nodes
            {"source": "abmap_train.embedding", "target": "custom_dnn_r1.embedding_input"},
            {"source": "abmap_train.embedding", "target": "custom_dnn_r2.embedding_input"},
            # haddock scores → custom_dnn labels (single-score per iteration)
            {"source": "haddock_r1.scores", "target": "custom_dnn_r1.labels"},
            {"source": "haddock_r2.scores", "target": "custom_dnn_r2.labels"},
            # loop_start → cdr_mutator
            {"source": "loop_start.heavy_chain", "target": "cdr_mutator.heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "cdr_mutator.light_chain"},
            # cdr_mutator variants → abmap_cand (batch embedding)
            {"source": "cdr_mutator.heavy_chain_variants", "target": "abmap_cand.candidate_sequences"},
            # abmap_cand.candidate_embeddings → both custom_dnn scoring nodes
            {"source": "abmap_cand.candidate_embeddings", "target": "custom_dnn_r1.candidate_embeddings"},
            {"source": "abmap_cand.candidate_embeddings", "target": "custom_dnn_r2.candidate_embeddings"},
            # custom_dnn candidate_predictions → loop_end UCB compute
            {"source": "custom_dnn_r1.candidate_predictions", "target": "loop_end.r1_preds"},
            {"source": "custom_dnn_r2.candidate_predictions", "target": "loop_end.r2_preds"},
            # loop_start chains → loop_end (fallback + pass-through)
            {"source": "loop_start.heavy_chain", "target": "loop_end.loop_start_heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "loop_end.loop_start_light_chain"},
        ],
    }

    # ── Insert into DB ────────────────────────────────────────────────────────
    now = datetime.datetime.utcnow().isoformat()
    pipeline_json = json.dumps(pipeline)

    conn.execute("DELETE FROM pipelines WHERE name=?", (pipeline["name"],))
    conn.execute(
        "INSERT INTO pipelines (id, name, data, created_at, updated_at) VALUES (?,?,?,?,?)",
        (pipeline_id, pipeline["name"], pipeline_json, now, now),
    )
    conn.commit()
    conn.close()
    print(f"Created pipeline: {pipeline_id}")
    print("Open the frontend → Pipelines list → 'Modular DNN · UCB Active Learning (Loop)'")


if __name__ == "__main__":
    main()
