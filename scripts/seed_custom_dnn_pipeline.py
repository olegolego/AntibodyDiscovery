"""Seed the Custom-DNN MLDE pipeline into the database.

Identical to the DNN-MLDE loop but uses the `custom_dnn` toolbox node with
committee_mode=True instead of the dedicated dnn_mlde node.  The user can open
the DNN Designer from the custom_dnn node's param panel to swap in any
architecture — MLP, Transformer, CNN, etc.

The pipeline collapses dnn_train + dnn_score into a single custom_dnn node that
receives both training embeddings/scores AND candidate embeddings, trains the
committee, and outputs acquisition_scores in one shot.

Run: python scripts/seed_custom_dnn_pipeline.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "protein_design.db"

# Default MLP architecture injected into the node params.
# Users can replace this via the DNN Designer — Input(512) must match AbMAP dim.
_DEFAULT_ARCH = {
    "version": "1.0",
    "nodes": [
        {"id": "input_0",  "type": "Input",   "params": {"features": 512},                          "position": {"x": 0,    "y": 0}},
        {"id": "linear_0", "type": "Linear",  "params": {"in_features": 512, "out_features": 256},  "position": {"x": 200,  "y": 0}},
        {"id": "relu_0",   "type": "ReLU",    "params": {},                                          "position": {"x": 350,  "y": 0}},
        {"id": "drop_0",   "type": "Dropout", "params": {"p": 0.2},                                  "position": {"x": 450,  "y": 0}},
        {"id": "linear_1", "type": "Linear",  "params": {"in_features": 256, "out_features": 128},  "position": {"x": 600,  "y": 0}},
        {"id": "relu_1",   "type": "ReLU",    "params": {},                                          "position": {"x": 750,  "y": 0}},
        {"id": "drop_1",   "type": "Dropout", "params": {"p": 0.2},                                  "position": {"x": 850,  "y": 0}},
        {"id": "linear_2", "type": "Linear",  "params": {"in_features": 128, "out_features": 64},   "position": {"x": 1000, "y": 0}},
        {"id": "relu_2",   "type": "ReLU",    "params": {},                                          "position": {"x": 1150, "y": 0}},
        {"id": "output_0", "type": "Output",  "params": {"out_features": 1, "task": "regression"},  "position": {"x": 1300, "y": 0}},
    ],
    "edges": [
        {"id": "e0", "source": "input_0",  "target": "linear_0"},
        {"id": "e1", "source": "linear_0", "target": "relu_0"},
        {"id": "e2", "source": "relu_0",   "target": "drop_0"},
        {"id": "e3", "source": "drop_0",   "target": "linear_1"},
        {"id": "e4", "source": "linear_1", "target": "relu_1"},
        {"id": "e5", "source": "relu_1",   "target": "drop_1"},
        {"id": "e6", "source": "drop_1",   "target": "linear_2"},
        {"id": "e7", "source": "linear_2", "target": "relu_2"},
        {"id": "e8", "source": "relu_2",   "target": "output_0"},
    ],
}

FEASIBILITY_CODE = """
import re

HYDROPHOBIC = set("VILMFYWAC")
CHARGED_POS = set("KRH")
CHARGED_NEG = set("DE")
AROMATIC    = set("FWY")

def n_glycosylation(seq):
    return bool(re.search(r"N[^P][ST]", seq))

def has_long_repeat(seq, n=5):
    return bool(re.search(r"(.)\\1{" + str(n - 1) + r",}", seq))

def net_charge(seq):
    return sum(1 for aa in seq if aa in CHARGED_POS) - sum(1 for aa in seq if aa in CHARGED_NEG)

def aromatic_fraction(seq):
    return sum(1 for aa in seq if aa in AROMATIC) / max(len(seq), 1)

def is_feasible(vh, vl=""):
    combined = (vh or "") + (vl or "")
    if n_glycosylation(combined):
        return False
    if has_long_repeat(combined):
        return False
    chg = net_charge(combined)
    if chg < -4 or chg > 4:
        return False
    if aromatic_fraction(combined) > 0.20:
        return False
    return True

feasible = {}
acq_scores = custom_dnn_acquisition_scores or {}

for vname in ["variant_1","variant_2","variant_3","variant_4","variant_5","variant_6","variant_7","variant_8"]:
    bundle_key = f"cdr_mutator_{vname}"
    bundle = locals().get(bundle_key) or {}
    vh = bundle.get("heavy_chain") or ""
    vl = bundle.get("light_chain") or ""
    if not vh:
        continue
    if is_feasible(vh, vl):
        acq = acq_scores.get(vh, -999.0)
        feasible[vh] = {"heavy_chain": vh, "light_chain": vl, "acquisition_score": acq}

if not feasible and acq_scores:
    best_vh = max(acq_scores, key=lambda k: acq_scores[k])
    feasible[best_vh] = {"heavy_chain": best_vh, "acquisition_score": acq_scores[best_vh]}

result = {"feasible_variants": feasible, "n_feasible": len(feasible), "n_total": 8}
"""

LOOP_END_CODE = """
feasible = feasibility_filter_feasible_variants or {}
acq_scores = custom_dnn_acquisition_scores or {}

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

# AbMAP embed for candidate sequences (after cdr_mutator)
ABMAP_CAND_CODE = """
import os
import json as _json
import urllib.request

ABMAP_URL = os.getenv("ABMAP_URL", "http://127.0.0.1:8005")

def embed_vh(sequence, num_mutations=5):
    payload = _json.dumps({
        "sequence": sequence, "chain_type": "H",
        "task": "structure", "embedding_type": "fixed",
        "num_mutations": num_mutations,
    }).encode()
    req = urllib.request.Request(
        f"{ABMAP_URL}/embed", data=payload,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return _json.loads(resp.read())["embedding"]

variants = cdr_mutator_heavy_chain_variants or []
candidate_embeddings = {}
errors = []

for i, vh in enumerate(variants):
    if not vh or vh in candidate_embeddings:
        continue
    try:
        emb = embed_vh(vh)
        candidate_embeddings[vh] = emb
        print(f"Embedded variant {i+1}: {vh[:20]}... ({len(emb)}d)")
    except Exception as e:
        errors.append(f"variant_{i+1}: {e}")
        print(f"Failed variant {i+1}: {e}")

result = {"candidate_embeddings": candidate_embeddings, "n_candidates": len(candidate_embeddings)}
"""


def main() -> None:
    conn = sqlite3.connect(str(DB_PATH))

    pipeline_id = "custom-dnn-mlde-" + str(uuid.uuid4())[:8]
    pipeline = {
        "id": pipeline_id,
        "name": "Custom DNN MLDE · Antibody Optimization (Loop)",
        "schema_version": "1",
        "nodes": [
            # ── Inputs ────────────────────────────────────────────────────────
            {
                "id": "loop_start",
                "tool": "loop_start",
                "params": {"max_iterations": 5},
                "position": {"x": 50.0, "y": 300.0},
            },
            {
                "id": "target_in",
                "tool": "target_input",
                "params": {},
                "position": {"x": 50.0, "y": 80.0},
            },
            # ── Structure prediction ───────────────────────────────────────────
            {
                "id": "immunebuilder",
                "tool": "immunebuilder",
                "params": {},
                "position": {"x": 300.0, "y": 300.0},
            },
            # ── Docking (4 parallel runs → 4 rank scores) ─────────────────────
            *[
                {
                    "id": f"haddock_r{i}",
                    "tool": "haddock3",
                    "params": {},
                    "position": {"x": 580.0, "y": (i - 1) * 140.0},
                }
                for i in range(1, 5)
            ],
            # ── AbMAP training embedding (current antibody) ────────────────────
            {
                "id": "abmap_train",
                "tool": "abmap",
                "params": {},
                "position": {"x": 300.0, "y": 140.0},
            },
            # ── CDR mutagenesis ────────────────────────────────────────────────
            {
                "id": "cdr_mutator",
                "tool": "cdr_mutator",
                "params": {"strategy": "blosum62", "n_variants": 8},
                "position": {"x": 860.0, "y": 300.0},
            },
            # ── AbMAP candidate embeddings ─────────────────────────────────────
            {
                "id": "abmap_cand",
                "tool": "compute",
                "params": {"code": ABMAP_CAND_CODE.strip()},
                "position": {"x": 1120.0, "y": 300.0},
            },
            # ── Custom DNN committee: trains on haddock scores + abmap,
            #    scores 8 candidates in one node ─────────────────────────────
            {
                "id": "custom_dnn",
                "tool": "custom_dnn",
                "params": {
                    "committee_mode": True,
                    "architecture_spec": _DEFAULT_ARCH,
                    "n_committee": 5,
                    "epochs": 150,
                    "learning_rate": 0.0005,
                    "batch_size": 128,
                    "kappa_epi": 2.0,
                    "kappa_conf": 0.5,
                    "top_k": 8,
                    "lower_is_better": True,
                },
                "position": {"x": 1380.0, "y": 210.0},
            },
            # ── Feasibility filter ─────────────────────────────────────────────
            {
                "id": "feasibility_filter",
                "tool": "compute",
                "params": {"code": FEASIBILITY_CODE.strip()},
                "position": {"x": 1640.0, "y": 210.0},
            },
            # ── Loop end ───────────────────────────────────────────────────────
            {
                "id": "loop_end",
                "tool": "loop_end",
                "params": {"code": LOOP_END_CODE.strip()},
                "position": {"x": 1900.0, "y": 210.0},
            },
        ],
        "edges": [
            # loop_start → immunebuilder + abmap_train + cdr_mutator
            {"id": "e1",  "source": "loop_start",   "target": "immunebuilder",  "sourceHandle": "heavy_chain", "targetHandle": "heavy_chain"},
            {"id": "e2",  "source": "loop_start",   "target": "immunebuilder",  "sourceHandle": "light_chain", "targetHandle": "light_chain"},
            {"id": "e3",  "source": "loop_start",   "target": "abmap_train",    "sourceHandle": "heavy_chain", "targetHandle": "heavy_chain"},
            {"id": "e4",  "source": "loop_start",   "target": "abmap_train",    "sourceHandle": "light_chain", "targetHandle": "light_chain"},
            {"id": "e5",  "source": "loop_start",   "target": "cdr_mutator",    "sourceHandle": "heavy_chain", "targetHandle": "heavy_chain"},
            {"id": "e6",  "source": "loop_start",   "target": "cdr_mutator",    "sourceHandle": "light_chain", "targetHandle": "light_chain"},
            # target → all 4 haddock runs
            {"id": "e7",  "source": "target_in",    "target": "haddock_r1",     "sourceHandle": "pdb",         "targetHandle": "antigen"},
            {"id": "e8",  "source": "target_in",    "target": "haddock_r2",     "sourceHandle": "pdb",         "targetHandle": "antigen"},
            {"id": "e9",  "source": "target_in",    "target": "haddock_r3",     "sourceHandle": "pdb",         "targetHandle": "antigen"},
            {"id": "e10", "source": "target_in",    "target": "haddock_r4",     "sourceHandle": "pdb",         "targetHandle": "antigen"},
            # immunebuilder → haddock
            {"id": "e11", "source": "immunebuilder","target": "haddock_r1",     "sourceHandle": "structure_1", "targetHandle": "antibody"},
            {"id": "e12", "source": "immunebuilder","target": "haddock_r2",     "sourceHandle": "structure_2", "targetHandle": "antibody"},
            {"id": "e13", "source": "immunebuilder","target": "haddock_r3",     "sourceHandle": "structure_3", "targetHandle": "antibody"},
            {"id": "e14", "source": "immunebuilder","target": "haddock_r4",     "sourceHandle": "structure_4", "targetHandle": "antibody"},
            # abmap_train embedding → custom_dnn.embeddings
            {"id": "e15", "source": "abmap_train",  "target": "custom_dnn",     "sourceHandle": "embedding",   "targetHandle": "embeddings"},
            # haddock scores → custom_dnn rank inputs
            {"id": "e16", "source": "haddock_r1",   "target": "custom_dnn",     "sourceHandle": "scores",      "targetHandle": "scores_rank_1"},
            {"id": "e17", "source": "haddock_r2",   "target": "custom_dnn",     "sourceHandle": "scores",      "targetHandle": "scores_rank_2"},
            {"id": "e18", "source": "haddock_r3",   "target": "custom_dnn",     "sourceHandle": "scores",      "targetHandle": "scores_rank_3"},
            {"id": "e19", "source": "haddock_r4",   "target": "custom_dnn",     "sourceHandle": "scores",      "targetHandle": "scores_rank_4"},
            # cdr_mutator → abmap_cand
            {"id": "e20", "source": "cdr_mutator",  "target": "abmap_cand",     "sourceHandle": "heavy_chain", "targetHandle": "heavy_chain"},
            {"id": "e21", "source": "cdr_mutator",  "target": "abmap_cand",     "sourceHandle": "light_chain", "targetHandle": "light_chain"},
            # abmap_cand candidate embeddings → custom_dnn.candidate_embeddings
            {"id": "e22", "source": "abmap_cand",   "target": "custom_dnn",     "sourceHandle": "candidate_embeddings", "targetHandle": "candidate_embeddings"},
            # custom_dnn acquisition_scores + variants → feasibility_filter
            {"id": "e23", "source": "custom_dnn",   "target": "feasibility_filter", "sourceHandle": "acquisition_scores", "targetHandle": "custom_dnn_acquisition_scores"},
            {"id": "e24", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_1",  "targetHandle": "cdr_mutator_variant_1"},
            {"id": "e25", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_2",  "targetHandle": "cdr_mutator_variant_2"},
            {"id": "e26", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_3",  "targetHandle": "cdr_mutator_variant_3"},
            {"id": "e27", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_4",  "targetHandle": "cdr_mutator_variant_4"},
            {"id": "e28", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_5",  "targetHandle": "cdr_mutator_variant_5"},
            {"id": "e29", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_6",  "targetHandle": "cdr_mutator_variant_6"},
            {"id": "e30", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_7",  "targetHandle": "cdr_mutator_variant_7"},
            {"id": "e31", "source": "cdr_mutator",  "target": "feasibility_filter", "sourceHandle": "variant_8",  "targetHandle": "cdr_mutator_variant_8"},
            # loop_end wiring
            {"id": "e32", "source": "loop_start",        "target": "loop_end", "sourceHandle": "heavy_chain",        "targetHandle": "loop_start_heavy_chain"},
            {"id": "e33", "source": "loop_start",        "target": "loop_end", "sourceHandle": "light_chain",        "targetHandle": "loop_start_light_chain"},
            {"id": "e34", "source": "feasibility_filter","target": "loop_end", "sourceHandle": "result",             "targetHandle": "feasibility_filter_result"},
            {"id": "e35", "source": "custom_dnn",        "target": "loop_end", "sourceHandle": "acquisition_scores", "targetHandle": "custom_dnn_acquisition_scores"},
        ],
    }

    schema = [r[1] for r in conn.execute("PRAGMA table_info(pipelines)").fetchall()]
    pipeline_json = json.dumps(pipeline)

    existing = conn.execute("SELECT id FROM pipelines WHERE name=?", (pipeline["name"],)).fetchone()
    if existing:
        conn.execute("UPDATE pipelines SET data=? WHERE id=?", (pipeline_json, existing[0]))
        print(f"Updated existing pipeline: {existing[0]}")
    else:
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        if "data" in schema:
            conn.execute(
                "INSERT INTO pipelines (id, name, data, created_at, updated_at) VALUES (?,?,?,?,?)",
                (pipeline_id, pipeline["name"], pipeline_json, now, now),
            )
        else:
            conn.execute(
                "INSERT INTO pipelines (id, name, created_at, updated_at) VALUES (?,?,?,?)",
                (pipeline_id, pipeline["name"], now, now),
            )
        print(f"Created new pipeline: {pipeline_id}")

    conn.commit()
    conn.close()
    print("Done. Load it from Pipelines → 'Custom DNN MLDE · Antibody Optimization (Loop)'")
    print("Tip: open the custom_dnn node's param panel → 'Design Architecture' to swap the MLP.")


if __name__ == "__main__":
    main()
