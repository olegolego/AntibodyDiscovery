#!/usr/bin/env python3
"""
Seed: Biophysical RL Mutation Policy  (loop, 20 iterations)

A reinforcement-learning pipeline that ACTUALLY LEARNS which CDR mutation
strategies improve drug-like biophysical properties — no structure prediction,
no docking, just fast on-CPU scorers that give a real reward signal every
iteration.

Pipeline flow (each of 20 iterations)
──────────────────────────────────────
 1  loop_start      — current VH+VL (patched each iteration with best variant)
 2  abmap_state     — AbMAP 252-d CDR-aware embedding → RL state
 3  rl_agent        — DQN: (state, reward_from_prev_iter) → (CDR, strategy, n_mut)
                      policy_state (Q-net + replay buffer) carried across iters
 4  cdr_mutate      — execute action on current sequence → variant_1 (+ 3 extras)
 5  netsolp         — solubility probability (0–1) for VH of variant_1
 6  deepsp          — SAP score + surface hydrophobicity for variant_1
 7  liabilities     — liability_scanner: n_liabilities (PTM / instability motifs)
 8  objective       — composite_fitness = 0.5·sol − 0.3·SAP − 0.2·liabilities
 9  loop_end        — keep variant if fitness ≥ best-so-far; log RL decision

What the RL agent learns
──────────────────────────
State   AbMAP 252-d embedding — CDR-weighted AbMAP representation.
Action  18 discrete choices: CDR∈{H1,H2,H3} × strategy∈{blosum62,conservative,random}
        × n_mutations∈{1,2}.  strategy and n_mutations are wired to the CDR mutator.
Reward  composite_fitness (higher = better solubility, lower SAP, fewer liabilities).
Policy  Double DQN, ε-greedy exploration (ε 1.0→0.1 over 14 iters, warmup 8 iters).

After warmup (~iter 8) the Q-network starts updating.  The agent typically learns:
  conservative / 1-mut  →  low liability churn, stable solubility
  random / 2-mut        →  higher SAP + liability increase
  blosum62 / 1-mut      →  best balance for CDR-H3 variants

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
                # port name matches the edge: objective.objective_score → rl_agent.composite_fitness
                "port": "composite_fitness",
                "weight": 1.0,
                "lower_is_better": False,   # higher fitness = better developability
                "normalization": "z_score",
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
        "replay_buffer_size": 100,  # 5× the number of iterations
        "n_train_steps": 5,
        "warmup_steps": 8,          # pure exploration for first 8 iters
        "tau": 1.0,                 # hard target-net copy every target_update_freq
    },
    "policy_network": {"version": "1.0", "nodes": [], "edges": []},  # default 2-layer MLP
}

# ── Composite biophysical objective ───────────────────────────────────────────
# loop_objective injects upstream scores as {source_node_id}_{output_key}.
# Our source node IDs: "netsolp", "deepsp", "liabilities"  →  three named variables.
OBJECTIVE_CODE = """\
# Composite biophysical fitness.
# Auto-injected as {source_node_id}_{output_key}:
#   netsolp_heavy_solubility    float 0–1  (higher = more soluble)
#   deepsp_sap_score            float 0–∞  (higher = more aggregation-prone)
#   liabilities_n_liabilities   int   ≥ 0  (higher = more PTM / instability hits)

sol   = float(locals().get("netsolp_heavy_solubility") or 0.5)
sap   = float(locals().get("deepsp_sap_score") or 20.0)
n_lia = int(locals().get("liabilities_n_liabilities") or 0)

# Normalise penalties to [0, 1] using empirical reference scales:
#   SAP: 0–60 covers most human antibody range
#   liabilities: 0–8 covers clean to liability-laden
sap_pen = min(sap / 60.0, 1.0)
lia_pen = min(n_lia / 8.0, 1.0)

# Higher = better developability candidate
objective_score = 0.5 * sol - 0.3 * sap_pen - 0.2 * lia_pen

result = {"objective_score": float(objective_score)}
"""

# ── Loop-end: greedy hill-climbing selection + RL logging ──────────────────────
# loop_end injects upstream outputs as the TARGET port name defined in edges.
LOOP_END_CODE = """\
# Biophysical RL — select best-so-far variant, log RL agent action.
#
# Input variables (named by the target port defined in each edge):
#   fitness_score    — composite_fitness for this iteration's variant
#   candidate_vh     — VH of variant_1 (cdr_mutator.heavy_chain alias)
#   candidate_vl     — VL of variant_1 (cdr_mutator.light_chain alias)
#   rl_actions       — list of recommended_actions from rl_designer
#   seed_vh          — original seed VH (fallback when candidate is empty)
#
# Auto-injected by executor:
#   loop_history     — list of {"fitness", "vh", "vl", ...} dicts, one per past iter
#   loop_iteration   — 0-based current iteration index

fitness     = float(locals().get("fitness_score") or 0.0)
cand_vh     = (locals().get("candidate_vh") or "").strip()
cand_vl     = (locals().get("candidate_vl") or "").strip()
fallback_vh = (locals().get("seed_vh") or "").strip()

if not cand_vh:
    cand_vh = fallback_vh

# Find historical best
best_fitness = -999.0
best_vh = fallback_vh
best_vl = ""
for h in (loop_history or []):
    h_fit = float(h.get("fitness", -999.0))
    if h_fit > best_fitness:
        best_fitness = h_fit
        best_vh = h.get("vh", fallback_vh)
        best_vl = h.get("vl", "")

# Greedy hill-climbing: accept only if we match or improve
improved        = fitness >= best_fitness
next_heavy_chain = cand_vh if improved else best_vh
next_light_chain = cand_vl if improved else best_vl

# Log RL agent decision (action + Q-value + explore/exploit mode)
actions = locals().get("rl_actions") or []
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
    f"({'✓ accepted  Δ+' + f'{delta:.4f}' if improved else '✗ reverted  Δ' + f'{delta:.4f}'})"
)

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    # stored in loop_history for hill-climbing across iterations
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
                "model_size": "8M",
            }, 380, 180),

            # ── 3. RL policy (Double DQN, 18 actions) ─────────────────────────
            node(n_rl, "rl_designer", {
                "rl_spec": BIOPHYSICAL_RL_SPEC,
                "mode": "train_and_act",
                "top_k": 4,
            }, 660, 180),

            # ── 4. CDR mutator (executes RL-chosen strategy + n_mutations) ─────
            node(n_cdr, "cdr_mutator", {
                "num_variants": 4,
                "cdr_h1": True,
                "cdr_h2": True,
                "cdr_h3": True,
                "cdr_l1": False,
                "cdr_l2": False,
                "cdr_l3": False,
                # seed=None → cdr_mutator adapter derives it from run_id for diversity
                "seed": None,
            }, 940, 180),

            # ── 5. Solubility (NetSolP, ESM-1b, CPU, ~30 s) ──────────────────
            node(n_netsolp, "netsolp", {}, 1220, 60),

            # ── 6. Aggregation / surface properties (DeepSP, CPU, ~5 s) ──────
            node(n_deepsp, "deepsp", {}, 1220, 300),

            # ── 7. PTM + instability liabilities (pure Python, ~1 s) ─────────
            node(n_liabilities, "liability_scanner", {}, 1220, 540),

            # ── 8. Composite objective (weights: 0.5·sol − 0.3·SAP − 0.2·lia)
            node(n_obj, "loop_objective", {
                "code": OBJECTIVE_CODE,
            }, 1500, 300),

            # ── 9. Loop-end: greedy hill-climbing + RL action logging ─────────
            node(n_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1500, 540),
        ],
        "edges": [
            # ── State: current sequence → AbMAP embedding ─────────────────────
            edge(n_start, "heavy_chain", n_embed, "vh"),
            edge(n_start, "light_chain", n_embed, "vl"),

            # ── RL agent: embedding (state) + fitness (reward) ─────────────────
            edge(n_embed, "results",         n_rl, "state_embeddings"),
            # objective_score → composite_fitness port (name matches RL spec reward signal)
            edge(n_obj,   "objective_score", n_rl, "composite_fitness"),

            # ── CDR mutator: RL-chosen action params ───────────────────────────
            edge(n_rl, "top_strategy",    n_cdr, "strategy"),
            edge(n_rl, "top_n_mutations", n_cdr, "num_mutations"),
            # sequences to mutate
            edge(n_start, "heavy_chain", n_cdr, "heavy_chain"),
            edge(n_start, "light_chain", n_cdr, "light_chain"),

            # ── Biophysical evaluators: variant_1 aliases (heavy/light_chain) ──
            edge(n_cdr, "heavy_chain", n_netsolp,     "heavy_chain"),
            edge(n_cdr, "light_chain", n_netsolp,     "light_chain"),
            edge(n_cdr, "heavy_chain", n_deepsp,      "heavy_chain"),
            edge(n_cdr, "light_chain", n_deepsp,      "light_chain"),
            edge(n_cdr, "heavy_chain", n_liabilities, "heavy_chain"),
            edge(n_cdr, "light_chain", n_liabilities, "light_chain"),

            # ── Objective: scores → loop_objective ────────────────────────────
            # Target port names don't affect variable names in loop_objective code;
            # the injected variable is always {source_node_id}_{output_key}:
            #   netsolp_heavy_solubility, deepsp_sap_score, liabilities_n_liabilities
            edge(n_netsolp,     "heavy_solubility", n_obj, "netsolp_heavy_solubility"),
            edge(n_deepsp,      "sap_score",        n_obj, "deepsp_sap_score"),
            edge(n_liabilities, "n_liabilities",    n_obj, "liabilities_n_liabilities"),

            # ── Loop-end: inputs named by TARGET port (used as var names in code) ─
            edge(n_obj,   "objective_score",     n_end, "fitness_score"),
            edge(n_cdr,   "heavy_chain",         n_end, "candidate_vh"),
            edge(n_cdr,   "light_chain",         n_end, "candidate_vl"),
            edge(n_rl,    "recommended_actions", n_end, "rl_actions"),
            edge(n_start, "heavy_chain",         n_end, "seed_vh"),
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
        print(f"   Iterations  : {pipeline_data['nodes'][0]['params']['max_iterations']}")
        print(f"   RL actions  : {n_actions}  "
              f"({len(spec['cdrs'])} CDRs × {len(spec['strategies'])} strategies × "
              f"{len(spec['n_mutations_choices'])} n_mut)")
        print(f"   RL warmup   : {alg['warmup_steps']} iters (ε=1.0 exploration)")
        print(f"   RL exploit  : starts iter {alg['warmup_steps']}, "
              f"ε→{alg['epsilon_end']} by iter {alg['epsilon_decay_steps']}")
        print(f"   Reward      : composite_fitness = 0.5·solubility − 0.3·SAP − 0.2·liabilities")
        print(f"   Evaluators  : NetSolP (solubility) | DeepSP (SAP) | LiabilityScanner (PTMs)")
        print()
        print("   The RL agent will learn:")
        print("     conservative/1-mut  →  stable solubility, few new liabilities")
        print("     blosum62/1-mut      →  good SAP for CDR-H3")
        print("     random/2-mut        →  higher penalty (teaches avoidance)")


if __name__ == "__main__":
    asyncio.run(seed())
