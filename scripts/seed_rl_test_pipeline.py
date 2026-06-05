#!/usr/bin/env python3
"""RL Test Pipeline — zero external dependencies, runs in ~3 minutes.

Verifies the complete RL learning loop end-to-end:
  state → Q-network → CDR action → mutation → scoring → reward → Q-update

Tools used (all local, no HTTP service, no GPU, no model download)
──────────────────────────────────────────────────────────────────
  loop_start       — pure Python backend venv
  aa_chem_embedding— 19-dim physicochemical embedding, backend venv
  rl_designer      — Double DQN, custom_dnn/.venv (torch)
  cdr_mutator      — biophi conda env (abnumber + sapiens)
  liability_scanner— pure Python backend venv  (~1 s per run)
  loop_objective   — pure Python backend venv
  loop_end         — pure Python backend venv

Usage
──────
    cd backend && .venv/bin/python ../scripts/seed_rl_test_pipeline.py
    # then open the canvas, load the pipeline, and click Run

What to look for when running
──────────────────────────────
  Iter 0–3   (warmup):   ε=1.0, random actions, buffer fills, no Q-updates
  Iter 4+    (learning): ε decays 1.0→0.1, first Q-updates, loss goes non-zero
  Iter 7+    (exploit):  agent picks CDRs with historically lower liability counts
  loop_end logs: "fitness=X  best=Y  ACCEPTED/REVERTED" shows hill-climbing
  rl_designer logs: "ε=X  buffer=N  loss=Y  top: CDR_H?/strategy (explore/exploit)"

The reward function: fitness = 1 / (1 + n_liabilities)
  0 liabilities  → fitness 1.00  (ideal, no PTM/instability hits)
  1 liability    → fitness 0.50
  2 liabilities  → fitness 0.33
  3+ liabilities → fitness ≤ 0.25

Since conservative mutations rarely introduce new liability motifs and random
mutations do, the agent should learn: conservative > blosum62 > random.
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


# ── Seed sequences ─────────────────────────────────────────────────────────────
# Human VH3-23 / Vk1-39 Fab with 2 known liability motifs (NxT deamidation in H2,
# NS in L1). This gives the agent real signal to work with — conservative mutations
# that avoid introducing new NxS/NxT, DP, or RGD motifs will score better.
SEED_VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGYTFTSYNMHWVRQAPGKGLEWVSYNIYPYNNVTNYADSVKGRFTISRDTSRNTAYLQMNSLRAEDTAVYYCAR"
    "GYYGSSGPYYWGQGTLVTVSS"
)
SEED_VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQSYSTPPTFGQGTKVEIK"
)

# ── RL spec ─────────────────────────────────────────────────────────────────────
# 2 CDRs × 2 strategies × 2 n_mutations = 8 discrete actions
# Small action space so the agent can explore fully within 8 iterations.
TEST_RL_SPEC = {
    "version": "1.0",
    "state": {
        "repr_type": "aa_chem",       # 19-dim physicochemical pooled embedding
        "dim": 19,
        "projection_dim": 0,
        "port": "state_embeddings",
    },
    "action": {
        "cdrs": ["H2", "H3"],
        "strategies": ["blosum62", "conservative"],
        "n_mutations_choices": [1, 2],
    },
    "reward": {
        "signals": [
            {
                "port": "composite_fitness",
                "weight": 1.0,
                "lower_is_better": False,
                # normalization=none: fitness already in [0, 1]
                "normalization": "none",
            }
        ],
        "shaping": "sparse",
    },
    "algorithm": {
        "kind": "dqn",
        "double_dqn": True,
        "target_update_freq": 3,
        "gamma": 0.9,
        "epsilon_start": 1.0,
        "epsilon_end": 0.1,
        "epsilon_decay": "linear",
        "epsilon_decay_steps": 4,   # iter 4–7: ε decays from 1.0 → 0.1
        "learning_rate": 0.005,
        "batch_size": 4,
        "replay_buffer_size": 50,
        "n_train_steps": 4,
        "warmup_steps": 4,          # iters 0–3: pure random exploration
        "tau": 1.0,
    },
    "policy_network": {"version": "1.0", "nodes": [], "edges": []},
}

# ── Scoring objective ──────────────────────────────────────────────────────────
# Reward = 1 / (1 + n_liabilities)
# Conservative mutations rarely introduce PTM / instability motifs.
# Random mutations are more likely to → agent learns to prefer conservative.
OBJECTIVE_CODE = """\
n_lia = int(locals().get("liabilities_n_liabilities") or 0)
# Smoother than a step function: 0 liabilities→1.0, 1→0.5, 2→0.33, 3→0.25
objective_score = 1.0 / (1.0 + n_lia)
result = {"objective_score": float(objective_score)}
"""

# ── Loop-end: greedy hill-climbing ────────────────────────────────────────────
LOOP_END_CODE = """\
# Variable names = {source_node_id}_{output_key}  (target port names are IGNORED by executor)
# Node IDs used here: start, objective, cdr_mutate, rl_agent
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

improved         = fitness >= best_fitness
next_heavy_chain = cand_vh if improved else best_vh
next_light_chain = cand_vl if improved else best_vl

# RL action log
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
    f"({'ACCEPTED' if improved else 'REVERTED'})"
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

    n_start       = "start"
    n_embed       = "embed"
    n_rl          = "rl_agent"
    n_cdr         = "cdr_mutate"
    n_liabilities = "liabilities"
    n_obj         = "objective"
    n_end         = "loop_end"

    pipeline_data = {
        "id": f"rl-test-{uid()}",
        "name": "RL Test Pipeline (Fast / Zero-Deps)",
        "schema_version": "1",
        "nodes": [
            # ── 1. Loop entry ──────────────────────────────────────────────────
            node(n_start, "loop_start", {
                "heavy_chain": SEED_VH,
                "light_chain": SEED_VL,
                "max_iterations": 8,
            }, 100, 300),

            # ── 2. State: 19-dim physicochemical embedding (no deps) ───────────
            node(n_embed, "aa_chem_embedding", {
                "pool_mode": "mean",
            }, 360, 180),

            # ── 3. RL DQN (8 actions) ─────────────────────────────────────────
            node(n_rl, "rl_designer", {
                "rl_spec": TEST_RL_SPEC,
                "mode": "train_and_act",
                "top_k": 4,
            }, 620, 180),

            # ── 4. CDR mutator: execute RL-chosen action ──────────────────────
            node(n_cdr, "cdr_mutator", {
                "num_variants": 1,   # 1 variant is enough for the test
                "seed": None,
            }, 880, 180),

            # ── 5. Liability scanner: pure Python, ~1 s ───────────────────────
            node(n_liabilities, "liability_scanner", {}, 1120, 180),

            # ── 6. Objective: fitness = 1 / (1 + n_liabilities) ──────────────
            node(n_obj, "loop_objective", {
                "code": OBJECTIVE_CODE,
            }, 1360, 180),

            # ── 7. Loop-end: greedy hill-climbing ─────────────────────────────
            node(n_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1360, 400),
        ],
        "edges": [
            # state embedding
            edge(n_start, "heavy_chain", n_embed, "heavy_chain"),
            edge(n_start, "light_chain", n_embed, "light_chain"),

            # RL state input
            edge(n_embed, "results", n_rl, "state_embeddings"),

            # CDR mutator: RL-chosen action
            edge(n_rl, "top_cdr",         n_cdr, "cdr_target"),
            edge(n_rl, "top_strategy",    n_cdr, "strategy"),
            edge(n_rl, "top_n_mutations", n_cdr, "num_mutations"),
            edge(n_start, "heavy_chain",  n_cdr, "heavy_chain"),
            edge(n_start, "light_chain",  n_cdr, "light_chain"),

            # scorer
            edge(n_cdr, "heavy_chain", n_liabilities, "heavy_chain"),
            edge(n_cdr, "light_chain", n_liabilities, "light_chain"),

            # objective
            edge(n_liabilities, "n_liabilities", n_obj, "liabilities_n_liabilities"),

            # loop-end inputs
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
        row = PipelineRow(
            id=pipeline.id,
            name=pipeline.name,
            data=json.dumps(pipeline.model_dump(mode="json")),
        )
        db.add(row)
        await db.commit()

    spec = TEST_RL_SPEC["action"]
    n_actions = (
        len(spec["cdrs"])
        * len(spec["strategies"])
        * len(spec["n_mutations_choices"])
    )
    alg = TEST_RL_SPEC["algorithm"]
    print(f"✓  Seeded: {pipeline_data['name']!r}  ({pipeline.id})")
    print(f"   Nodes       : {len(pipeline_data['nodes'])}")
    print(f"   Edges       : {len(pipeline_data['edges'])}")
    print()
    print(f"   Iterations  : 8  (fast, ~2–4 min total)")
    print(f"   RL actions  : {n_actions}  "
          f"({len(spec['cdrs'])} CDRs × {len(spec['strategies'])} strategies × "
          f"{len(spec['n_mutations_choices'])} n_mut)")
    print(f"   State dim   : 19  (aa_chem_embedding — no HTTP, no model download)")
    print(f"   Reward      : 1/(1+n_liabilities)  (liability_scanner, pure Python)")
    print()
    print(f"   Warmup  iters 0–{alg['warmup_steps']-1}: random exploration (ε=1.0)")
    print(f"   Learning iters {alg['warmup_steps']}–7: Q-updates, ε decays to {alg['epsilon_end']}")
    print()
    print("   Expected behaviour:")
    print("     conservative/1-mut → fewest new liability motifs → highest reward")
    print("     random/2-mut       → most new motifs → lowest reward (agent avoids)")
    print()
    print("   What to check in the run logs:")
    print("     rl_designer: 'buffer=N' should grow each iteration after iter 0")
    print("     rl_designer: 'loss=X' goes non-zero after warmup (iter 4)")
    print("     loop_end:    'ε=...' should decay from 1.0 → 0.1 over iters 4–7")
    print("     loop_end:    fitness values + ACCEPTED/REVERTED per iteration")


if __name__ == "__main__":
    asyncio.run(seed())
