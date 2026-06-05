#!/usr/bin/env python3
"""Seed: Biophysical RL Mutation Policy  (loop, 20 iterations)

A reinforcement-learning pipeline that ACTUALLY LEARNS which CDR mutation
strategies improve drug-like biophysical properties — no structure prediction,
no docking, just fast on-CPU scorers that give a real reward signal every
iteration.

Pipeline flow (each of 20 iterations)
──────────────────────────────────────
 1  loop_start      — current VH+VL (patched each iteration with best variant)
 2  abmap_state     — AbMAP 252-d CDR-aware embedding → RL state
 3  rl_agent        — DQN: state → (CDR, strategy, n_mut) action
                      reward_signals injected by loop_executor from previous
                      iteration's composite_fitness (one-step lag design)
                      policy_state carried across iters automatically
 4  cdr_mutate      — execute RL-chosen CDR + strategy + n_mutations
 5  netsolp         — solubility probability (0–1) for VH of variant_1
 6  deepsp          — SAP score + surface hydrophobicity for variant_1
 7  liabilities     — PTM / instability motifs
 8  objective       — composite_fitness = 0.5·sol − 0.3·SAP − 0.2·liabilities
 9  loop_end        — greedy hill-climbing; log RL decision

What the RL agent learns
──────────────────────────
State   AbMAP 252-d embedding — CDR-weighted AbMAP representation.
Action  18 discrete choices: CDR∈{H1,H2,H3} × strategy∈{blosum62,conservative,random}
        × n_mutations∈{1,2}.
        top_cdr → cdr_mutate.cdr_target  (only the RL-selected CDR is mutated)
        top_strategy → cdr_mutate.strategy
        top_n_mutations → cdr_mutate.num_mutations
Reward  composite_fitness from previous iteration (injected by loop_executor).
        normalization=none — fitness is already bounded [-0.2, 0.5].

How reward flows
──────────────────
The DAG within each iteration is strictly acyclic.  Reward reaches the RL
agent via the loop executor (not an edge within the same iteration):
  iter N: rl_agent acts → cdr_mutate → evaluate → loop_end (stores score)
  iter N+1: loop_executor injects reward_signals={composite_fitness: {vh_N: score_N}}
            into rl_agent.params before the run starts

After warmup (~iter 8) the Q-network starts updating.  The agent typically learns:
  conservative / 1-mut  →  low liability churn, stable solubility
  blosum62 / 1-mut      →  good SAP for CDR-H3
  random / 2-mut        →  higher penalty (teaches avoidance)

Usage
──────
    cd backend && .venv/bin/python ../scripts/seed_biophysical_rl_pipeline.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def uid() -> str:
    return str(uuid.uuid4())[:8]


def node(id_: str, tool: str, params: dict, x: float, y: float) -> dict:
    return {"id": id_, "tool": tool, "params": params, "position": {"x": x, "y": y}}


def edge(src: str, src_port: str, tgt: str, tgt_port: str) -> dict:
    return {"source": f"{src}.{src_port}", "target": f"{tgt}.{tgt_port}"}


# ── Seed antibody sequences ────────────────────────────────────────────────────
# Human VH3-23 / Vk1-39 Fab framework — common therapeutic scaffold.
# CDRs (IMGT): H1=GYTFTSY, H2=INPNSGGT, H3=ARQGYYDSSGYYY
# Starting solubility and SAP are mid-range — real headroom for improvement.
SEED_VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGYTFTSYNMHWVRQAPGKGLEWVSYNIYPYNNVTNYADSVKGRFTISRDTSRNTAYLQMNSLRAEDTAVYYCAR"
    "GYYGSSGPYYWGQGTLVTVSS"
)
SEED_VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQSYSTPPTFGQGTKVEIK"
)

# ── RL spec ────────────────────────────────────────────────────────────────────
# 3 CDRs × 3 strategies × 2 n_mutations = 18 discrete actions
BIOPHYSICAL_RL_SPEC = {
    "version": "1.0",
    "state": {
        "repr_type": "abmap",
        "dim": 252,
        "projection_dim": 0,
        "port": "state_embeddings",
    },
    "action": {
        "cdrs": ["H1", "H2", "H3"],
        "strategies": ["blosum62", "conservative", "random"],
        "n_mutations_choices": [1, 2],
    },
    "reward": {
        "signals": [
            {
                # "composite_fitness" matches the port name injected by loop_executor
                "port": "composite_fitness",
                "weight": 1.0,
                "lower_is_better": False,
                # normalization=none: fitness is already in [-0.2, 0.5] from the objective
                # formula.  z_score with 1 sample per iteration would always produce 0.
                "normalization": "none",
            }
        ],
        "shaping": "sparse",
    },
    "algorithm": {
        "kind": "dqn",
        "double_dqn": True,
        "target_update_freq": 5,
        "gamma": 0.95,              # short episode horizon (1 step per iteration)
        "epsilon_start": 1.0,
        "epsilon_end": 0.1,
        "epsilon_decay": "linear",
        "epsilon_decay_steps": 14,  # fully transitioned to exploit by iter 14
        "learning_rate": 0.001,
        "batch_size": 8,
        "replay_buffer_size": 100,
        "n_train_steps": 5,
        "warmup_steps": 8,          # pure exploration for first 8 iters
        "tau": 1.0,
    },
    "policy_network": {"version": "1.0", "nodes": [], "edges": []},
}

# ── Composite biophysical objective ───────────────────────────────────────────
# Injected variable names: {source_node_id}_{output_key}
OBJECTIVE_CODE = """\
# Composite biophysical fitness.
# Injected as {source_node_id}_{output_key}:
#   netsolp_heavy_solubility    float 0–1  (higher = more soluble)
#   deepsp_sap_score            float 0–∞  (higher = more aggregation-prone)
#   liabilities_n_liabilities   int   ≥ 0  (more PTM / instability hits)

sol   = float(locals().get("netsolp_heavy_solubility") or 0.5)
sap   = float(locals().get("deepsp_sap_score") or 20.0)
n_lia = int(locals().get("liabilities_n_liabilities") or 0)

# Normalise penalties to [0, 1] using empirical antibody ranges
sap_pen = min(sap / 60.0, 1.0)
lia_pen = min(n_lia / 8.0, 1.0)

# Higher = better developability
objective_score = 0.5 * sol - 0.3 * sap_pen - 0.2 * lia_pen

result = {"objective_score": float(objective_score)}
"""

# ── Loop-end: greedy hill-climbing + RL logging ────────────────────────────────
LOOP_END_CODE = """\
# Variable names = {source_node_id}_{output_key}  (target port names are IGNORED by executor)
# Node IDs: start="start", objective="objective", cdr="cdr_mutate", rl="rl_agent"
# Auto-injected: loop_history, loop_iteration

fitness     = float(locals().get("objective_objective_score") or 0.0)
cand_vh     = (locals().get("cdr_mutate_heavy_chain") or "").strip()
cand_vl     = (locals().get("cdr_mutate_light_chain") or "").strip()
fallback_vh = (locals().get("start_heavy_chain") or "").strip()
fallback_vl = (locals().get("start_light_chain") or "").strip()

if not cand_vh:
    cand_vh = fallback_vh
if not cand_vl:
    cand_vl = fallback_vl

best_fitness = -999.0
best_vh = fallback_vh
best_vl = fallback_vl
for h in (loop_history or []):
    h_fit = float(h.get("fitness", h.get("objective_score", -999.0)))
    if h_fit > best_fitness:
        best_fitness = h_fit
        best_vh = h.get("vh", fallback_vh) or fallback_vh
        best_vl = h.get("vl", fallback_vl) or fallback_vl

improved        = fitness >= best_fitness
next_heavy_chain = cand_vh if improved else best_vh
next_light_chain = cand_vl if improved else best_vl

actions = locals().get("rl_agent_recommended_actions") or []
if actions:
    top = actions[0]
    print(
        f"[iter {loop_iteration}]  RL  "
        f"{top.get('cdr','?')}/{top.get('strategy','?')}/{top.get('n_mutations','?')}mut  "
        f"Q={top.get('q_value', 0.0):.3f}  "
        f"({'explore' if top.get('exploratory') else 'exploit'})"
    )

delta = fitness - best_fitness
print(
    f"[iter {loop_iteration}]  fitness={fitness:.4f}  "
    f"best={max(fitness, best_fitness):.4f}  "
    f"({'ACCEPTED Δ+' + f'{delta:.4f}' if improved else 'REVERTED Δ' + f'{delta:.4f}'})"
)

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    "fitness": fitness,
    "vh": cand_vh,
    "vl": cand_vl,
}
"""


async def seed() -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.pipeline import Pipeline

    # ── Node IDs ───────────────────────────────────────────────────────────────
    n_start       = "start"
    n_embed       = "abmap_state"
    n_rl          = "rl_agent"
    n_cdr         = "cdr_mutate"
    n_netsolp     = "netsolp"
    n_deepsp      = "deepsp"
    n_liabilities = "liabilities"
    n_obj         = "objective"
    n_end         = "loop_end"

    pipeline_data = {
        "id": f"biophysical-rl-mutation-{uid()}",
        "name": "Biophysical RL Mutation Policy",
        "schema_version": "1",
        "nodes": [
            # ── 1. Loop entry ──────────────────────────────────────────────────
            node(n_start, "loop_start", {
                "heavy_chain": SEED_VH,
                "light_chain": SEED_VL,
                "max_iterations": 20,
            }, 100, 320),

            # ── 2. State encoder (AbMAP 252-d CDR embedding) ───────────────────
            node(n_embed, "abmap", {
                "task": "structure",
            }, 380, 180),

            # ── 3. RL policy (Double DQN, 18 actions) ─────────────────────────
            # reward_signals for this node are injected by the loop executor
            # from the previous iteration's composite_fitness — no direct edge
            # needed (and none possible without creating a DAG cycle).
            node(n_rl, "rl_designer", {
                "rl_spec": BIOPHYSICAL_RL_SPEC,
                "mode": "train_and_act",
                "top_k": 4,
            }, 660, 180),

            # ── 4. CDR mutator: RL-chosen CDR + strategy + n_mutations ─────────
            # cdr_target is wired from rl_agent.top_cdr so only the selected CDR
            # is mutated (not all heavy CDRs simultaneously).
            node(n_cdr, "cdr_mutator", {
                "num_variants": 4,
                "seed": None,
            }, 940, 180),

            # ── 5. Solubility (NetSolP, CPU, ~30 s) ──────────────────────────
            node(n_netsolp, "netsolp", {}, 1220, 60),

            # ── 6. Aggregation propensity (DeepSP, CPU, ~5 s) ────────────────
            node(n_deepsp, "deepsp", {}, 1220, 300),

            # ── 7. PTM + instability liabilities (pure Python, ~1 s) ─────────
            node(n_liabilities, "liability_scanner", {}, 1220, 540),

            # ── 8. Composite objective (0.5·sol − 0.3·SAP − 0.2·lia) ─────────
            node(n_obj, "loop_objective", {
                "code": OBJECTIVE_CODE,
            }, 1500, 300),

            # ── 9. Loop-end: greedy hill-climbing + RL action logging ─────────
            node(n_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1500, 540),
        ],
        "edges": [
            # ── State: both chains → AbMAP embedding ──────────────────────────
            edge(n_start, "heavy_chain", n_embed, "vh"),
            edge(n_start, "light_chain", n_embed, "vl"),

            # ── RL agent: embedding as state ───────────────────────────────────
            # NOTE: reward_signals are NOT wired here — they arrive from the
            # loop executor (previous-iteration composite_fitness).  Wiring
            # objective_score → rl_agent within the same iteration would create
            # a DAG cycle and the pipeline would fail to start.
            edge(n_embed, "results", n_rl, "state_embeddings"),

            # ── CDR mutator: RL-chosen action params ───────────────────────────
            edge(n_rl, "top_cdr",         n_cdr, "cdr_target"),    # which CDR to mutate
            edge(n_rl, "top_strategy",    n_cdr, "strategy"),
            edge(n_rl, "top_n_mutations", n_cdr, "num_mutations"),
            edge(n_start, "heavy_chain",  n_cdr, "heavy_chain"),
            edge(n_start, "light_chain",  n_cdr, "light_chain"),

            # ── Biophysical evaluators: variant_1 convenience aliases ──────────
            edge(n_cdr, "heavy_chain", n_netsolp,     "heavy_chain"),
            edge(n_cdr, "light_chain", n_netsolp,     "light_chain"),
            edge(n_cdr, "heavy_chain", n_deepsp,      "heavy_chain"),
            edge(n_cdr, "light_chain", n_deepsp,      "light_chain"),
            edge(n_cdr, "heavy_chain", n_liabilities, "heavy_chain"),
            edge(n_cdr, "light_chain", n_liabilities, "light_chain"),

            # ── Objective: scores → loop_objective ────────────────────────────
            # Variables injected as {source_node_id}_{output_key}:
            #   netsolp_heavy_solubility, deepsp_sap_score, liabilities_n_liabilities
            edge(n_netsolp,     "heavy_solubility", n_obj, "netsolp_heavy_solubility"),
            edge(n_deepsp,      "sap_score",        n_obj, "deepsp_sap_score"),
            edge(n_liabilities, "n_liabilities",    n_obj, "liabilities_n_liabilities"),

            # ── Loop-end: inputs named by TARGET port (used as vars in code) ───
            edge(n_obj,   "objective_score",     n_end, "fitness_score"),
            edge(n_cdr,   "heavy_chain",         n_end, "candidate_vh"),
            edge(n_cdr,   "light_chain",         n_end, "candidate_vl"),
            edge(n_rl,    "recommended_actions", n_end, "rl_actions"),
            edge(n_start, "heavy_chain",         n_end, "seed_vh"),
            edge(n_start, "light_chain",         n_end, "seed_vl"),
        ],
    }

    pipeline = Pipeline.model_validate(pipeline_data)

    async with AsyncSessionLocal() as db:
        from app.db.models import PipelineRow
        existing = await db.get(PipelineRow, pipeline.id)
        if existing:
            print(f"Pipeline {pipeline.id} already exists — skipping.")
            return

        row = PipelineRow(
            id=pipeline.id,
            name=pipeline.name,
            data=json.dumps(pipeline.model_dump(mode="json")),
        )
        db.add(row)
        await db.commit()

        spec = BIOPHYSICAL_RL_SPEC["action"]
        n_actions = len(spec["cdrs"]) * len(spec["strategies"]) * len(spec["n_mutations_choices"])
        alg = BIOPHYSICAL_RL_SPEC["algorithm"]
        print(f"✓  Seeded: {pipeline.name!r}  ({pipeline.id})")
        print(f"   Nodes       : {len(pipeline.nodes)}")
        print(f"   Edges       : {len(pipeline.edges)}")
        print(f"   Iterations  : 20")
        print(f"   RL actions  : {n_actions}  "
              f"({len(spec['cdrs'])} CDRs × {len(spec['strategies'])} strategies × "
              f"{len(spec['n_mutations_choices'])} n_mut)")
        print(f"   RL warmup   : {alg['warmup_steps']} iters (ε=1.0 exploration)")
        print(f"   RL exploit  : starts iter {alg['warmup_steps']}, "
              f"ε→{alg['epsilon_end']} by iter {alg['epsilon_decay_steps']}")
        print(f"   Reward port : composite_fitness (normalization=none)")
        print(f"   Reward lag  : 1 iter (injected by loop_executor, NOT a DAG edge)")
        print()
        print("   Scorers: NetSolP (solubility) | DeepSP (SAP) | LiabilityScanner (PTMs)")
        print("   The RL agent will learn:")
        print("     conservative/1-mut  →  low liability churn, stable solubility")
        print("     blosum62/1-mut      →  good SAP balance for CDR-H3")
        print("     random/2-mut        →  higher penalty (agent learns avoidance)")


if __name__ == "__main__":
    asyncio.run(seed())
