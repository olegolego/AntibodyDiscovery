"""Seed the RL Informed Mutation pipeline template.

Usage:
    cd backend && .venv/bin/python ../scripts/seed_rl_pipeline.py

Pipeline (loop, 10 iterations)
────────────────────────────────
 1  loop_start      — entry sequence (VH), patched each iteration with the selected variant
 2  abmap           — AbMAP 252d embedding of the current sequence (state for RL)
 3  rl_designer     — DQN policy: receives embedding as state, outputs (CDR, strategy, n_mut)
                      policy_state (Q-net weights + replay buffer) accumulated across iterations
 4  cdr_mutator     — executes the chosen action: mutates the CDR with the chosen strategy
 5  immunebuilder   — predict structure for the best CDR variant
 6  haddock3        — dock against the antigen; score feeds back as reward
 7  loop_end        — compute node: pick best variant by haddock score → next_heavy_chain

Loop: 10 iterations. On iteration 0 the RL agent explores randomly (ε=1.0). From iteration 1
onwards it trains on the growing replay buffer and decays ε toward exploitation.
The HADDOCK3 docking score (lower is better) is used as the reward signal.

RL state
──────────
AbMAP 252d embedding of the current (evaluated) sequence. This gives the policy a compact,
CDR-aware representation of the antibody.

RL action
──────────
(CDR_H3, blosum62, 2 mutations) as the default starting point — |A| = 6*2*2 = 24 discrete
actions (3 CDRs × 2 strategies × 2 n_mutations).  All hypers are visible in the RL Designer
and can be changed without editing this script.

Reward
──────────
HADDOCK3 docking score (lower is better, sign-flipped internally by rl_designer).
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


# ── Default RLSpec ────────────────────────────────────────────────────────────
DEFAULT_RL_SPEC = {
    "version": "1.0",
    "state": {
        "repr_type": "abmap",
        "dim": 252,
        "projection_dim": 0,
        "port": "state_embeddings",
    },
    "action": {
        "cdrs": ["H2", "H3", "L3"],
        "strategies": ["blosum62", "conservative"],
        "n_mutations_choices": [1, 2],
    },
    "reward": {
        "signals": [
            {
                "port": "haddock_score",
                "weight": 1.0,
                "lower_is_better": True,
                "normalization": "z_score",
            }
        ],
        "shaping": "sparse",
    },
    "algorithm": {
        "kind": "dqn",
        "double_dqn": True,
        "target_update_freq": 5,
        "gamma": 0.99,
        "epsilon_start": 1.0,
        "epsilon_end": 0.1,
        "epsilon_decay": "linear",
        "epsilon_decay_steps": 8,
        "learning_rate": 0.001,
        "batch_size": 8,
        "replay_buffer_size": 500,
        "n_train_steps": 10,
        "warmup_steps": 8,
        "tau": 1.0,
    },
    "policy_network": {"version": "1.0", "nodes": [], "edges": []},
}

# ── Loop-end compute code ─────────────────────────────────────────────────────
LOOP_END_CODE = '''
# Select the CDR variant with the best (lowest) HADDOCK score.
# Variables injected by loop_end adapter (use them directly, no "inputs" dict):
#   haddock3_score         — dict {seq_id: float} or scalar
#   rl_recommended_actions — list from rl_designer (for logging)
#   loop_start_heavy_chain — current seed sequence
#   loop_history           — list of previous iterations (injected automatically)
#   loop_iteration         — current 0-based iteration index

score_raw = locals().get("haddock3_score") or {}
if isinstance(score_raw, (int, float)):
    score_raw = {"seq_0": score_raw}
if not isinstance(score_raw, dict):
    score_raw = {}

# Select the variant with the lowest docking score
if score_raw:
    best_seq = min(score_raw, key=lambda k: score_raw[k])
    best_score = score_raw[best_seq]
else:
    best_seq = locals().get("loop_start_heavy_chain", "") or ""
    best_score = None

# Log what the RL agent recommended
rl_actions = locals().get("rl_recommended_actions") or []
if rl_actions:
    top = rl_actions[0]
    print(f"RL agent chose {top.get('cdr')}/{top.get('strategy')}/{top.get('n_mutations')}mut "
          f"({'explore' if top.get('exploratory') else 'exploit'}, Q={top.get('q_value', 0):.3f})")

print(f"Iteration {locals().get('loop_iteration', 0)}: best_seq={best_seq!r}, best_score={best_score}")

result = {
    "next_heavy_chain": best_seq,
    "best_score": best_score,
}
'''


async def seed() -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.pipeline import Pipeline

    # Node IDs
    n_loop_start = "loop_start"
    n_abmap = "abmap_state"
    n_rl = "rl_agent"
    n_cdr = "cdr_mutate"
    n_immunebuilder = "immunebuilder_r1"
    n_haddock = "haddock_r1"
    n_loop_end = "loop_end"

    pipeline_data = {
        "id": f"rl-informed-mutation-{uid()}",
        "name": "RL Informed Mutation (Loop)",
        "schema_version": "1",
        "nodes": [
            node(n_loop_start, "loop_start", {
                "heavy_chain": "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS",
                "light_chain": "",
                "max_iterations": 10,
            }, 50, 300),

            node(n_abmap, "abmap", {
                "task": "structure",
                "model_size": "8M",
            }, 320, 200),

            node(n_rl, "rl_designer", {
                "rl_spec": DEFAULT_RL_SPEC,
                "mode": "train_and_act",
                "top_k": 4,
            }, 560, 200),

            node(n_cdr, "cdr_mutator", {
                "num_variants": 4,
                # strategy/CDR wired from rl_designer outputs
                "seed": None,
            }, 800, 200),

            node(n_immunebuilder, "immunebuilder", {}, 1050, 200),

            node(n_haddock, "haddock3", {
                "antigen_active_residues": "",
            }, 1300, 200),

            node(n_loop_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1050, 420),
        ],
        "edges": [
            # Sequence → AbMAP embedding (state)
            edge(n_loop_start, "heavy_chain", n_abmap, "vh"),

            # AbMAP results → RL agent (state)
            edge(n_abmap, "results", n_rl, "state_embeddings"),

            # RL agent top action → CDR mutator params
            edge(n_rl, "top_strategy", n_cdr, "strategy"),

            # Seed sequence → CDR mutator
            edge(n_loop_start, "heavy_chain", n_cdr, "heavy_chain"),

            # CDR mutator variants → ImmuneBuilder
            edge(n_cdr, "variant_1", n_immunebuilder, "heavy_chain"),

            # ImmuneBuilder → HADDOCK3
            edge(n_immunebuilder, "structure_1", n_haddock, "antibody"),

            # HADDOCK3 score → loop_end (for sequence selection)
            edge(n_haddock, "scores", n_loop_end, "haddock3_score"),

            # RL recommended actions → loop_end (for logging)
            edge(n_rl, "recommended_actions", n_loop_end, "rl_recommended_actions"),

            # Seed sequence → loop_end (fallback)
            edge(n_loop_start, "heavy_chain", n_loop_end, "loop_start_heavy_chain"),
        ],
    }

    pipeline = Pipeline.model_validate(pipeline_data)

    async with AsyncSessionLocal() as db:
        from app.db.models import PipelineRow
        existing = await db.get(PipelineRow, pipeline.id)
        if existing:
            print(f"Pipeline {pipeline.id} already exists, skipping.")
            return

        row = PipelineRow(
            id=pipeline.id,
            name=pipeline.name,
            data=json.dumps(pipeline.model_dump(mode="json")),
        )
        db.add(row)
        await db.commit()
        print(f"✓ Seeded pipeline: {pipeline.name!r} ({pipeline.id})")
        print(f"  Nodes : {len(pipeline.nodes)}")
        print(f"  Edges : {len(pipeline.edges)}")
        print(f"  RL spec action count: "
              f"{len(DEFAULT_RL_SPEC['action']['cdrs'])} CDRs × "
              f"{len(DEFAULT_RL_SPEC['action']['strategies'])} strategies × "
              f"{len(DEFAULT_RL_SPEC['action']['n_mutations_choices'])} n_mut = "
              f"{len(DEFAULT_RL_SPEC['action']['cdrs']) * len(DEFAULT_RL_SPEC['action']['strategies']) * len(DEFAULT_RL_SPEC['action']['n_mutations_choices'])} actions")


if __name__ == "__main__":
    asyncio.run(seed())
