#!/usr/bin/env python3
"""Seed looped active-learning pipelines and submit them as test runs."""
import json, sqlite3, uuid, requests
from datetime import datetime

DB   = "backend/protein_design.db"
API  = "http://localhost:8000"
NOW  = datetime.utcnow().isoformat()

VH = "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS"
VL = "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK"

LOOP_END_DEVFILTER = """\
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
    "selected_score": acq_scores.get(next_heavy_chain),
    "iteration": loop_iteration,
    "n_feasible": len(feasible),
}
"""

LOOP_END_DIRECT = """\
acq = dnn_score_acquisition_scores or {}

if acq:
    best_vh = max(acq, key=lambda k: float(acq.get(k, -999)))
    next_heavy_chain = best_vh
    next_light_chain = loop_start_light_chain
else:
    next_heavy_chain = loop_start_heavy_chain
    next_light_chain = loop_start_light_chain

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    "n_candidates": len(acq),
    "best_score": acq.get(next_heavy_chain),
    "iteration": loop_iteration,
}
"""

COLLECT_IGLM_CODE = """\
variants = []
for i in range(1, 6):
    v = locals().get(f"iglm_variant_{i}")
    if v and isinstance(v, dict) and v.get("heavy_chain"):
        h = v["heavy_chain"].strip()
        if h and h not in variants:
            variants.append(h)
# heavy_chain_variants must be a list so abmap_cand enters candidate-batch mode
result = {"heavy_chain_variants": variants}
"""


def node(nid, tool, params, x, y):
    return {"id": nid, "tool": tool, "params": params, "position": {"x": float(x), "y": float(y)}}

def edge(src, tgt):
    return {"source": src, "target": tgt}


# ── Pipeline 1: Biophysical Properties AL Loop ────────────────────────────────
pipe_biophys = {
    "id": "pipe-loop-biophys",
    "name": "Biophysical Properties Active Learning Loop",
    "schema_version": "1",
    "nodes": [
        node("loop_start",           "loop_start",           {"heavy_chain": VH, "light_chain": VL, "max_iterations": 5}, 50, 300),
        node("abmap_train",          "abmap",                {"chain_type": "H", "task": "structure"}, 330, 100),
        node("deepsp_r1",            "deepsp",               {}, 330, 280),
        node("netsolp_r2",           "netsolp",              {}, 330, 460),
        node("cdr_mutator",          "cdr_mutator",          {"n_variants": 8, "strategy": "blosum62", "n_mutations": 3}, 330, 640),
        node("abmap_cand",           "abmap",                {"chain_type": "H", "task": "structure"}, 610, 640),
        node("dnn_train",            "dnn_mlde",             {"mode": "train+score", "n_committee": 5, "epochs": 100, "lower_is_better": True}, 610, 280),
        node("dnn_score",            "dnn_mlde",             {"mode": "score"}, 890, 280),
        node("developability_filter","developability_filter",{"max_ptm_liabilities": 15}, 1170, 280),
        node("loop_end",             "loop_end",             {"code": LOOP_END_DEVFILTER}, 1450, 280),
    ],
    "edges": [
        edge("loop_start.heavy_chain",  "abmap_train.heavy_chain"),
        edge("loop_start.heavy_chain",  "deepsp_r1.heavy_chain"),
        edge("loop_start.light_chain",  "deepsp_r1.light_chain"),
        edge("loop_start.heavy_chain",  "netsolp_r2.heavy_chain"),
        edge("loop_start.light_chain",  "netsolp_r2.light_chain"),
        edge("loop_start.heavy_chain",  "cdr_mutator.heavy_chain"),
        edge("loop_start.light_chain",  "cdr_mutator.light_chain"),
        edge("abmap_train.results",      "dnn_train.embeddings"),
        edge("deepsp_r1.sap_score",     "dnn_train.scores_rank_1"),
        edge("netsolp_r2.heavy_solubility", "dnn_train.scores_rank_2"),
        edge("cdr_mutator.heavy_chain_variants", "abmap_cand.sequence"),
        edge("abmap_cand.results",               "dnn_score.candidate_embeddings"),
        edge("dnn_train.model_artifact",         "dnn_score.model_artifact"),
        edge("dnn_score.acquisition_scores",     "developability_filter.acquisition_scores"),
        *[edge(f"cdr_mutator.variant_{i}", f"developability_filter.variant_{i}") for i in range(1, 9)],
        edge("loop_start.heavy_chain",           "developability_filter.heavy_chain"),
        edge("loop_start.heavy_chain",           "loop_end.code"),
        edge("loop_start.light_chain",           "loop_end.code"),
        edge("developability_filter.feasible_variants", "loop_end.code"),
        edge("dnn_score.acquisition_scores",     "loop_end.code"),
    ],
}

# ── Pipeline 2: Humanization Optimization Loop ───────────────────────────────
pipe_humanize = {
    "id": "pipe-loop-humanize-opt",
    "name": "Humanization Optimization Active Learning Loop",
    "schema_version": "1",
    "nodes": [
        node("loop_start",           "loop_start",           {"heavy_chain": VH, "light_chain": VL, "max_iterations": 5}, 50, 300),
        node("abmap_train",          "abmap",                {"chain_type": "H", "task": "structure"}, 330, 100),
        node("biophi_r1",            "biophi",               {"iterations": 1}, 330, 280),
        node("liability_r2",         "liability_scanner",    {}, 330, 460),
        node("cdr_mutator",          "cdr_mutator",          {"n_variants": 8, "strategy": "blosum62", "n_mutations": 3}, 330, 640),
        node("abmap_cand",           "abmap",                {"chain_type": "H", "task": "structure"}, 610, 640),
        node("dnn_train",            "dnn_mlde",             {"mode": "train+score", "n_committee": 5, "epochs": 100, "lower_is_better": True}, 610, 280),
        node("dnn_score",            "dnn_mlde",             {"mode": "score"}, 890, 280),
        node("developability_filter","developability_filter",{"max_ptm_liabilities": 15}, 1170, 280),
        node("loop_end",             "loop_end",             {"code": LOOP_END_DEVFILTER}, 1450, 280),
    ],
    "edges": [
        edge("loop_start.heavy_chain",  "abmap_train.heavy_chain"),
        edge("loop_start.heavy_chain",  "biophi_r1.heavy_chain"),
        edge("loop_start.light_chain",  "biophi_r1.light_chain"),
        edge("loop_start.heavy_chain",  "liability_r2.heavy_chain"),
        edge("loop_start.light_chain",  "liability_r2.light_chain"),
        edge("loop_start.heavy_chain",  "cdr_mutator.heavy_chain"),
        edge("loop_start.light_chain",  "cdr_mutator.light_chain"),
        edge("abmap_train.results",           "dnn_train.embeddings"),
        edge("biophi_r1.heavy_mutations",    "dnn_train.scores_rank_1"),
        edge("liability_r2.n_liabilities",   "dnn_train.scores_rank_2"),
        edge("cdr_mutator.heavy_chain_variants", "abmap_cand.sequence"),
        edge("abmap_cand.results",               "dnn_score.candidate_embeddings"),
        edge("dnn_train.model_artifact",         "dnn_score.model_artifact"),
        edge("dnn_score.acquisition_scores",     "developability_filter.acquisition_scores"),
        *[edge(f"cdr_mutator.variant_{i}", f"developability_filter.variant_{i}") for i in range(1, 9)],
        edge("loop_start.heavy_chain",           "developability_filter.heavy_chain"),
        edge("loop_start.heavy_chain",           "loop_end.code"),
        edge("loop_start.light_chain",           "loop_end.code"),
        edge("developability_filter.feasible_variants", "loop_end.code"),
        edge("dnn_score.acquisition_scores",     "loop_end.code"),
    ],
}

# ── Pipeline 3: IgLM CDR-H3 Redesign + Biophysics Loop ───────────────────────
pipe_iglm = {
    "id": "pipe-loop-iglm-biophys",
    "name": "IgLM CDR-H3 Redesign + Biophysics Active Learning Loop",
    "schema_version": "1",
    "nodes": [
        node("loop_start",     "loop_start",    {"heavy_chain": VH, "light_chain": VL, "max_iterations": 5}, 50, 300),
        node("iglm",           "iglm",          {"mode": "infill", "infill_region": "cdr_h3", "redesign_chain": "vh", "num_sequences": 5, "temperature": 1.0, "species": "human"}, 330, 300),
        node("abmap_train",    "abmap",         {"chain_type": "H", "task": "structure"}, 610, 100),
        node("deepsp_r1",      "deepsp",        {}, 610, 300),
        node("biophi_r2",      "biophi",        {"iterations": 1}, 610, 480),
        node("collect_variants","compute",      {"code": COLLECT_IGLM_CODE}, 610, 660),
        node("abmap_cand",     "abmap",         {"chain_type": "H", "task": "structure"}, 890, 660),
        node("dnn_train",      "dnn_mlde",      {"mode": "train+score", "n_committee": 5, "epochs": 100, "lower_is_better": True}, 890, 280),
        node("dnn_score",      "dnn_mlde",      {"mode": "score"}, 1170, 280),
        node("loop_end",       "loop_end",      {"code": LOOP_END_DIRECT}, 1450, 280),
    ],
    "edges": [
        edge("loop_start.heavy_chain", "iglm.heavy_chain"),
        edge("loop_start.light_chain", "iglm.light_chain"),
        # Score and embed the CURRENT (loop_start) sequence — not the IgLM variant
        edge("loop_start.heavy_chain", "abmap_train.heavy_chain"),
        edge("loop_start.heavy_chain", "deepsp_r1.heavy_chain"),
        edge("loop_start.light_chain", "deepsp_r1.light_chain"),
        edge("loop_start.heavy_chain", "biophi_r2.heavy_chain"),
        edge("loop_start.light_chain", "biophi_r2.light_chain"),
        # Collect IgLM variants → batch embed as candidates
        *[edge(f"iglm.variant_{i}", f"collect_variants.iglm_variant_{i}") for i in range(1, 6)],
        edge("collect_variants.heavy_chain_variants", "abmap_cand.sequence"),
        # DNN training
        edge("abmap_train.results",      "dnn_train.embeddings"),
        edge("deepsp_r1.sap_score",      "dnn_train.scores_rank_1"),
        edge("biophi_r2.heavy_mutations","dnn_train.scores_rank_2"),
        edge("abmap_cand.results",              "dnn_score.candidate_embeddings"),
        edge("dnn_train.model_artifact",        "dnn_score.model_artifact"),
        # Loop end — direct acquisition score selection (no dev filter)
        edge("loop_start.heavy_chain",    "loop_end.code"),
        edge("loop_start.light_chain",    "loop_end.code"),
        edge("dnn_score.acquisition_scores", "loop_end.code"),
    ],
}

# ── Pipeline 4: Triple-Rank Biophysics DNN Loop ───────────────────────────────
pipe_trirank = {
    "id": "pipe-loop-trirank",
    "name": "Triple-Rank Biophysics Active Learning Loop",
    "schema_version": "1",
    "nodes": [
        node("loop_start",           "loop_start",           {"heavy_chain": VH, "light_chain": VL, "max_iterations": 5}, 50, 350),
        node("abmap_train",          "abmap",                {"chain_type": "H", "task": "structure"}, 330, 100),
        node("deepsp_r1",            "deepsp",               {}, 330, 280),
        node("netsolp_r2",           "netsolp",              {}, 330, 460),
        node("biophi_r3",            "biophi",               {"iterations": 1}, 330, 640),
        node("cdr_mutator",          "cdr_mutator",          {"n_variants": 8, "strategy": "blosum62", "n_mutations": 3}, 330, 820),
        node("abmap_cand",           "abmap",                {"chain_type": "H", "task": "structure"}, 610, 820),
        node("dnn_train",            "dnn_mlde",             {"mode": "train+score", "n_committee": 5, "epochs": 100, "lower_is_better": True}, 610, 370),
        node("dnn_score",            "dnn_mlde",             {"mode": "score"}, 890, 370),
        node("developability_filter","developability_filter",{"max_ptm_liabilities": 15}, 1170, 370),
        node("loop_end",             "loop_end",             {"code": LOOP_END_DEVFILTER}, 1450, 370),
    ],
    "edges": [
        edge("loop_start.heavy_chain",  "abmap_train.heavy_chain"),
        edge("loop_start.heavy_chain",  "deepsp_r1.heavy_chain"),
        edge("loop_start.light_chain",  "deepsp_r1.light_chain"),
        edge("loop_start.heavy_chain",  "netsolp_r2.heavy_chain"),
        edge("loop_start.light_chain",  "netsolp_r2.light_chain"),
        edge("loop_start.heavy_chain",  "biophi_r3.heavy_chain"),
        edge("loop_start.light_chain",  "biophi_r3.light_chain"),
        edge("loop_start.heavy_chain",  "cdr_mutator.heavy_chain"),
        edge("loop_start.light_chain",  "cdr_mutator.light_chain"),
        edge("abmap_train.results",           "dnn_train.embeddings"),
        edge("deepsp_r1.sap_score",          "dnn_train.scores_rank_1"),
        edge("netsolp_r2.heavy_solubility",  "dnn_train.scores_rank_2"),
        edge("biophi_r3.heavy_mutations",    "dnn_train.scores_rank_3"),
        edge("cdr_mutator.heavy_chain_variants", "abmap_cand.sequence"),
        edge("abmap_cand.results",               "dnn_score.candidate_embeddings"),
        edge("dnn_train.model_artifact",         "dnn_score.model_artifact"),
        edge("dnn_score.acquisition_scores",     "developability_filter.acquisition_scores"),
        *[edge(f"cdr_mutator.variant_{i}", f"developability_filter.variant_{i}") for i in range(1, 9)],
        edge("loop_start.heavy_chain",           "developability_filter.heavy_chain"),
        edge("loop_start.heavy_chain",           "loop_end.code"),
        edge("loop_start.light_chain",           "loop_end.code"),
        edge("developability_filter.feasible_variants", "loop_end.code"),
        edge("dnn_score.acquisition_scores",     "loop_end.code"),
    ],
}

CUSTOM_OBJECTIVE_CODE = """\
# All upstream scoring outputs are available as {node_id}_{key} variables.
# Define your composite objective here (lower = better, matches dnn lower_is_better=True).
sap          = float(deepsp_r1_sap_score or 0)
solubility   = float(netsolp_r2_heavy_solubility or 0)
mutations    = float(biophi_r3_heavy_mutations or 0)

# SAP: lower is better (hydrophobicity penalty)
# Solubility: higher is better → flip to penalize low solubility
# Mutations: fewer is better
objective_score = 0.4 * sap + 0.4 * (1.0 - solubility) + 0.2 * mutations

result = {"objective_score": objective_score}
"""

LOOP_END_CUSTOM_OBJ = """\
acq = dnn_score_acquisition_scores or {}

if acq:
    best_vh = min(acq, key=lambda k: float(acq.get(k, 999)))
    next_heavy_chain = best_vh
    next_light_chain = loop_start_light_chain
else:
    next_heavy_chain = loop_start_heavy_chain
    next_light_chain = loop_start_light_chain

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    "n_candidates": len(acq),
    "best_objective": acq.get(next_heavy_chain),
    "iteration": loop_iteration,
}
"""

# ── Pipeline 5: Custom Objective Function Loop ────────────────────────────────
pipe_custom_obj = {
    "id": "pipe-loop-custom-obj",
    "name": "Custom Objective Function Active Learning Loop",
    "schema_version": "1",
    "nodes": [
        node("loop_start",   "loop_start",      {"heavy_chain": VH, "light_chain": VL, "max_iterations": 5}, 50, 350),
        node("abmap_train",  "abmap",            {"chain_type": "H", "task": "structure"}, 330, 100),
        node("deepsp_r1",    "deepsp",           {}, 330, 300),
        node("netsolp_r2",   "netsolp",          {}, 330, 480),
        node("biophi_r3",    "biophi",           {"iterations": 1}, 330, 660),
        node("objective",    "loop_objective",   {"code": CUSTOM_OBJECTIVE_CODE}, 610, 480),
        node("cdr_mutator",  "cdr_mutator",      {"n_variants": 8, "strategy": "blosum62", "n_mutations": 3}, 330, 840),
        node("abmap_cand",   "abmap",            {"chain_type": "H", "task": "structure"}, 610, 840),
        node("dnn_train",    "dnn_mlde",         {"mode": "train+score", "n_committee": 5, "epochs": 100, "lower_is_better": True}, 890, 350),
        node("dnn_score",    "dnn_mlde",         {"mode": "score"}, 1170, 350),
        node("loop_end",     "loop_end",         {"code": LOOP_END_CUSTOM_OBJ}, 1450, 350),
    ],
    "edges": [
        edge("loop_start.heavy_chain",  "abmap_train.heavy_chain"),
        edge("loop_start.heavy_chain",  "deepsp_r1.heavy_chain"),
        edge("loop_start.light_chain",  "deepsp_r1.light_chain"),
        edge("loop_start.heavy_chain",  "netsolp_r2.heavy_chain"),
        edge("loop_start.light_chain",  "netsolp_r2.light_chain"),
        edge("loop_start.heavy_chain",  "biophi_r3.heavy_chain"),
        edge("loop_start.light_chain",  "biophi_r3.light_chain"),
        edge("loop_start.heavy_chain",  "cdr_mutator.heavy_chain"),
        edge("loop_start.light_chain",  "cdr_mutator.light_chain"),
        # Scores feed into objective node
        edge("deepsp_r1.sap_score",         "objective.code"),
        edge("netsolp_r2.heavy_solubility", "objective.code"),
        edge("biophi_r3.heavy_mutations",   "objective.code"),
        # Objective → DNN training (single rank)
        edge("abmap_train.results",           "dnn_train.embeddings"),
        edge("objective.objective_score",    "dnn_train.scores_rank_1"),
        # Candidates → DNN scoring
        edge("cdr_mutator.heavy_chain_variants", "abmap_cand.sequence"),
        edge("abmap_cand.results",               "dnn_score.candidate_embeddings"),
        edge("dnn_train.model_artifact",         "dnn_score.model_artifact"),
        # Loop control
        edge("loop_start.heavy_chain",       "loop_end.code"),
        edge("loop_start.light_chain",       "loop_end.code"),
        edge("dnn_score.acquisition_scores", "loop_end.code"),
    ],
}

PIPELINES = [pipe_biophys, pipe_humanize, pipe_iglm, pipe_trirank, pipe_custom_obj]

# ── Seed into DB ──────────────────────────────────────────────────────────────
conn = sqlite3.connect(DB)
for p in PIPELINES:
    conn.execute(
        "INSERT OR REPLACE INTO pipelines (id, name, data, created_at, updated_at) VALUES (?,?,?,?,?)",
        (p["id"], p["name"], json.dumps(p), NOW, NOW),
    )
conn.commit()
conn.close()
print(f"Seeded {len(PIPELINES)} pipelines.")

# ── Submit only the new custom-objective pipeline as a test run ───────────────
run_ids = {}
for p in [pipe_custom_obj]:
    r = requests.post(f"{API}/api/runs/", json=p, timeout=30)
    r.raise_for_status()
    run = r.json()
    run_ids[p["id"]] = run["id"]
    loop_id = run.get("loop_id", "—")
    print(f"  {p['name'][:55]:55s}  run={run['id'][:8]}  loop={str(loop_id)[:8]}")

print("\nRun IDs:", json.dumps(run_ids, indent=2))
