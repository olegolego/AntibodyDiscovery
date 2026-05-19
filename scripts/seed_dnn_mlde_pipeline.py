"""Seed the DNN-MLDE pipeline into the database.

Creates a new pipeline that is identical to the running RCC-MLDE loop but
with rcc_mlde nodes replaced by dnn_mlde nodes pre-trained on the AL_results
dataset (4a239ca5-ec85-43ab-b8bb-601c5526ed87).

Key differences from the RCC-MLDE pipeline:
  - dnn_mlde (DynamicDNN committee) replaces rcc_mlde (Ridge committee)
  - abmap tool node replaces the inline abmap_cand compute node
  - developability_filter tool replaces the inline feasibility_filter compute node

Run: python scripts/seed_dnn_mlde_pipeline.py
The new pipeline appears in the frontend under "DNN-MLDE · Antibody Optimization (Loop)".
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "protein_design.db"
SOURCE_LOOP_ID = "b7fc778c-1567-48b2-81fd-01484866210a"
AL_DATASET_ID  = "4a239ca5-ec85-43ab-b8bb-601c5526ed87"

LOOP_END_CODE = """
feasible = developability_filter_feasible_variants or {}
acq_scores = dnn_score_acquisition_scores or {}

ranked = sorted(feasible.values(), key=lambda v: v.get("acquisition_score", -999), reverse=True)

if ranked:
    best = ranked[0]
    next_heavy_chain = best["heavy_chain"]
    next_light_chain = best.get("light_chain") or loop_start_light_chain
else:
    next_heavy_chain = loop_start_heavy_chain
    next_light_chain = loop_start_light_chain

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    "selected_acquisition_score": acq_scores.get(next_heavy_chain, None),
    "iteration_summary": {
        "iteration": loop_iteration,
        "n_feasible": len(feasible),
        "n_scored": len(acq_scores),
        "selected_vh_prefix": next_heavy_chain[:20] if next_heavy_chain else None,
    },
}
"""


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))

    # ── Load source pipeline snapshot ─────────────────────────────────────────
    row = conn.execute(
        "SELECT pipeline_snapshot FROM loop_runs WHERE id=?", (SOURCE_LOOP_ID,)
    ).fetchone()
    if not row:
        print(f"ERROR: source loop {SOURCE_LOOP_ID} not found in {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    snap: dict = json.loads(row[0])
    pdb_content = ""
    for node in snap["nodes"]:
        if node["id"] == "target_in":
            pdb_content = (node.get("params") or {}).get("pdb", "")
            break

    loop_start_params = {}
    for node in snap["nodes"]:
        if node["id"] == "loop_start":
            loop_start_params = dict(node.get("params") or {})
            break
    # Cap at 2 iterations for the test run
    loop_start_params["max_iterations"] = 2

    haddock_residues = ""
    for node in snap["nodes"]:
        if node["id"] == "haddock_r1":
            haddock_residues = (node.get("params") or {}).get("antigen_active_residues", "")
            break

    cdr_params = {}
    for node in snap["nodes"]:
        if node["id"] == "cdr_mutator":
            cdr_params = node.get("params") or {}
            break

    # ── Build new pipeline ────────────────────────────────────────────────────
    pipeline_id = "dnn-mlde-" + str(uuid.uuid4())[:8]
    pipeline = {
        "id": pipeline_id,
        "name": "DNN-MLDE · Antibody Optimization (Loop)",
        "schema_version": "1",
        "nodes": [
            {
                "id": "loop_start",
                "tool": "loop_start",
                "params": loop_start_params,
                "position": {"x": 50.0, "y": 300.0},
            },
            {
                "id": "target_in",
                "tool": "target_input",
                "params": {"pdb": pdb_content},
                "position": {"x": 50.0, "y": 80.0},
            },
            {
                "id": "immunebuilder",
                "tool": "immunebuilder",
                "params": {},
                "position": {"x": 300.0, "y": 300.0},
            },
            *[
                {
                    "id": f"haddock_r{i}",
                    "tool": "haddock3",
                    "params": {"antigen_active_residues": haddock_residues},
                    "position": {"x": 580.0, "y": (i - 1) * 140.0},
                }
                for i in range(1, 5)
            ],
            {
                "id": "abmap_train",
                "tool": "abmap",
                "params": {},
                "position": {"x": 300.0, "y": 140.0},
            },
            {
                "id": "dnn_train",
                "tool": "dnn_mlde",
                "params": {
                    "mode": "train",
                    "pretrain_dataset_id": AL_DATASET_ID,
                    "n_committee": 5,
                    "epochs": 150,
                    "lr": 0.0005,
                    "batch_size": 128,
                    "kappa_epi": 2.0,
                    "kappa_conf": 0.5,
                    "top_k": 50,
                    "lower_is_better": True,
                },
                "position": {"x": 860.0, "y": 210.0},
            },
            {
                "id": "cdr_mutator",
                "tool": "cdr_mutator",
                "params": cdr_params,
                "position": {"x": 1120.0, "y": 210.0},
            },
            # AbMAP tool node — embeds CDR variants via candidate_sequences input
            {
                "id": "abmap_cand",
                "tool": "abmap",
                "params": {"chain_type": "H", "num_mutations": 5},
                "position": {"x": 1380.0, "y": 210.0},
            },
            # DNN score node — runs inference with trained committee
            {
                "id": "dnn_score",
                "tool": "dnn_mlde",
                "params": {
                    "mode": "score",
                    "n_committee": 5,
                    "kappa_epi": 2.0,
                    "kappa_conf": 0.5,
                    "top_k": 8,
                    "lower_is_better": True,
                },
                "position": {"x": 1600.0, "y": 210.0},
            },
            # Developability filter — research-backed liability checks
            {
                "id": "developability_filter",
                "tool": "developability_filter",
                "params": {
                    "max_ptm_liabilities": 3,
                    "hard_fail_checks": ["N-glycosylation", "Unpaired-Cys", "Homopolymer"],
                },
                "position": {"x": 1820.0, "y": 210.0},
            },
            {
                "id": "loop_end",
                "tool": "loop_end",
                "params": {"code": LOOP_END_CODE.strip()},
                "position": {"x": 2060.0, "y": 210.0},
            },
        ],
        # Edges use "node_id.port_name" format for both source and target —
        # this is what PipelineEdge expects and what the executor splits on.
        "edges": [
            # Loop start → immunebuilder + abmap_train
            {"source": "loop_start.heavy_chain", "target": "immunebuilder.heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "immunebuilder.light_chain"},
            {"source": "loop_start.heavy_chain", "target": "abmap_train.heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "abmap_train.light_chain"},
            # target → all 4 haddock runs
            {"source": "target_in.pdb", "target": "haddock_r1.antigen"},
            {"source": "target_in.pdb", "target": "haddock_r2.antigen"},
            {"source": "target_in.pdb", "target": "haddock_r3.antigen"},
            {"source": "target_in.pdb", "target": "haddock_r4.antigen"},
            # immunebuilder structures → haddock
            {"source": "immunebuilder.structure_1", "target": "haddock_r1.antibody"},
            {"source": "immunebuilder.structure_2", "target": "haddock_r2.antibody"},
            {"source": "immunebuilder.structure_3", "target": "haddock_r3.antibody"},
            {"source": "immunebuilder.structure_4", "target": "haddock_r4.antibody"},
            # abmap + scores → dnn_train
            {"source": "abmap_train.embedding",   "target": "dnn_train.embeddings"},
            {"source": "haddock_r1.scores",        "target": "dnn_train.scores_rank_1"},
            {"source": "haddock_r2.scores",        "target": "dnn_train.scores_rank_2"},
            {"source": "haddock_r3.scores",        "target": "dnn_train.scores_rank_3"},
            {"source": "haddock_r4.scores",        "target": "dnn_train.scores_rank_4"},
            # loop_start → cdr_mutator
            {"source": "loop_start.heavy_chain", "target": "cdr_mutator.heavy_chain"},
            {"source": "loop_start.light_chain",  "target": "cdr_mutator.light_chain"},
            # cdr_mutator.heavy_chain_variants → abmap_cand.candidate_sequences
            {"source": "cdr_mutator.heavy_chain_variants", "target": "abmap_cand.candidate_sequences"},
            # abmap_cand.candidate_embeddings + model_artifact → dnn_score
            {"source": "abmap_cand.candidate_embeddings", "target": "dnn_score.candidate_embeddings"},
            {"source": "dnn_train.model_artifact",         "target": "dnn_score.model_artifact"},
            # dnn_score.acquisition_scores → developability_filter
            {"source": "dnn_score.acquisition_scores", "target": "developability_filter.acquisition_scores"},
            # cdr_mutator variants → developability_filter
            {"source": "cdr_mutator.variant_1", "target": "developability_filter.variant_1"},
            {"source": "cdr_mutator.variant_2", "target": "developability_filter.variant_2"},
            {"source": "cdr_mutator.variant_3", "target": "developability_filter.variant_3"},
            {"source": "cdr_mutator.variant_4", "target": "developability_filter.variant_4"},
            {"source": "cdr_mutator.variant_5", "target": "developability_filter.variant_5"},
            {"source": "cdr_mutator.variant_6", "target": "developability_filter.variant_6"},
            {"source": "cdr_mutator.variant_7", "target": "developability_filter.variant_7"},
            {"source": "cdr_mutator.variant_8", "target": "developability_filter.variant_8"},
            # loop_end wiring (all inputs via compute-mode prefix expansion)
            {"source": "loop_start.heavy_chain",            "target": "loop_end.loop_start_heavy_chain"},
            {"source": "loop_start.light_chain",             "target": "loop_end.loop_start_light_chain"},
            {"source": "developability_filter.feasible_variants", "target": "loop_end.developability_filter_feasible_variants"},
            {"source": "dnn_score.acquisition_scores",       "target": "loop_end.dnn_score_acquisition_scores"},
        ],
    }

    # ── Insert into pipelines table ───────────────────────────────────────────
    schema = [r[1] for r in conn.execute("PRAGMA table_info(pipelines)").fetchall()]
    pipeline_json = json.dumps(pipeline)

    import datetime
    now = datetime.datetime.utcnow().isoformat()

    # Delete any existing pipeline(s) with this name so we get a clean row
    # with a consistent id (row id == JSON data id).
    conn.execute("DELETE FROM pipelines WHERE name=?", (pipeline["name"],))

    conn.execute(
        "INSERT INTO pipelines (id, name, data, created_at, updated_at) VALUES (?,?,?,?,?)",
        (pipeline_id, pipeline["name"], pipeline_json, now, now),
    )
    print(f"Created pipeline: {pipeline_id}")

    conn.commit()
    conn.close()
    print("Done. Open the frontend → Runs page → Pipelines, or load it from the canvas.")


if __name__ == "__main__":
    main()
