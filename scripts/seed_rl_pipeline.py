"""Seed the RL Informed Mutation (Docking) pipeline template.

Usage:
    cd backend && .venv/bin/python ../scripts/seed_rl_pipeline.py

Pipeline (loop, 10 iterations)
────────────────────────────────
 1  loop_start      — entry VH+VL, patched each iteration with the selected variant
 2  target_input    — antigen PDB (spike RBD default; wire to HADDOCK3)
 3  abmap_state     — AbMAP 252-d embedding of current VH+VL (RL state)
 4  rl_agent        — DQN: state → (CDR, strategy, n_mut)
                      policy_state accumulated across iterations
                      reward_signals injected by loop_executor from previous
                      iteration's HADDOCK3 score (one-step lag)
 5  cdr_mutate      — execute RL-chosen action (CDR + strategy + n_mutations)
 6  immunebuilder   — predict structure for the best CDR variant
 7  haddock3        — dock against the antigen; score feeds back as reward
 8  loop_end        — select best variant by HADDOCK score → next_heavy_chain + next_light_chain

Loop: 10 iterations.  On iteration 0 the RL agent explores randomly (ε=1.0).
From iteration 1 onwards the executor injects the previous HADDOCK score as
reward_signals and the agent trains on the growing replay buffer.

RL state  : AbMAP 252-d CDR-aware embedding of the current evaluated sequence.
RL action : 3 CDRs × 2 strategies × 2 n_mutations = 12 actions.
            top_cdr → cdr_mutate.cdr_target (only the selected CDR is mutated).
Reward    : HADDOCK3 docking score (lower is better; loop_executor sign-flips
            internally via lower_is_better=True, normalization=none).
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
# VH3-23 / Vk1-39 anti-spike Fab scaffold (IMGT numbering)
SEED_VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS"
)
SEED_VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK"
)

# ── RL spec ─────────────────────────────────────────────────────────────────────
# 3 CDRs × 2 strategies × 2 n_mutations = 12 discrete actions
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
                "lower_is_better": True,    # lower HADDOCK score = better binding
                # normalization=none: HADDOCK scores typically range -200 to 0;
                # z_score with 1 sample per iteration produces reward=0 always.
                "normalization": "none",
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
LOOP_END_CODE = '''\
# Variable names = {source_node_id}_{output_key}  (target port names are IGNORED)
# Node IDs: loop_start="loop_start", haddock="haddock_r1", rl="rl_agent"
# Auto-injected: loop_history, loop_iteration

score_raw = locals().get("haddock_r1_scores") or {}
if isinstance(score_raw, (int, float)):
    score_raw = {"seq_0": score_raw}
if isinstance(score_raw, dict) and "score" in score_raw:
    score_raw = {"seq_0": float(score_raw["score"])}
if not isinstance(score_raw, dict):
    score_raw = {}

fallback_vh = (locals().get("loop_start_heavy_chain") or "").strip()
fallback_vl = (locals().get("loop_start_light_chain") or "").strip()

if score_raw:
    best_seq = min(score_raw, key=lambda k: score_raw[k])
    best_score = score_raw[best_seq]
else:
    best_seq = fallback_vh
    best_score = None

# RL action logging
rl_actions = locals().get("rl_agent_recommended_actions") or []
if rl_actions:
    top = rl_actions[0]
    print(
        f"[iter {loop_iteration}]  RL  "
        f"{top.get('cdr','?')}/{top.get('strategy','?')}/{top.get('n_mutations','?')}mut  "
        f"Q={top.get('q_value', 0.0):.3f}  "
        f"({'explore' if top.get('exploratory') else 'exploit'})"
    )

print(f"[iter {loop_iteration}]  best_seq={best_seq[:20]!r}…  best_score={best_score}")

result = {
    "next_heavy_chain": best_seq if best_seq and best_seq != fallback_vh else fallback_vh,
    "next_light_chain": fallback_vl,  # VL unchanged — CDR mutator handles VH CDRs
    "best_score": best_score,
    "vh": best_seq or fallback_vh,
    "vl": fallback_vl,
}
'''


async def seed() -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.pipeline import Pipeline

    # Node IDs
    n_loop_start = "loop_start"
    n_target     = "target_input"
    n_abmap      = "abmap_state"
    n_rl         = "rl_agent"
    n_cdr        = "cdr_mutate"
    n_immune     = "immunebuilder_r1"
    n_haddock    = "haddock_r1"
    n_loop_end   = "loop_end"

    pipeline_data = {
        "id": f"rl-docking-mutation-{uid()}",
        "name": "RL Informed Mutation (Docking Loop)",
        "schema_version": "1",
        "nodes": [
            # ── 1. Loop entry — VH + VL ───────────────────────────────────────
            node(n_loop_start, "loop_start", {
                "heavy_chain": SEED_VH,
                "light_chain": SEED_VL,
                "max_iterations": 10,
            }, 50, 320),

            # ── 2. Antigen target (spike RBD default) ─────────────────────────
            # Change target in the canvas to dock against a different antigen.
            node(n_target, "target_input", {}, 50, 120),

            # ── 3. AbMAP embedding (RL state) ─────────────────────────────────
            node(n_abmap, "abmap", {
                "task": "structure",
            }, 320, 200),

            # ── 4. RL DQN policy (12 actions) ─────────────────────────────────
            # reward_signals = {haddock_score: {vh: score}} injected by loop_executor
            node(n_rl, "rl_designer", {
                "rl_spec": DEFAULT_RL_SPEC,
                "mode": "train_and_act",
                "top_k": 4,
            }, 560, 200),

            # ── 5. CDR mutator: execute RL-chosen CDR + strategy + n_mut ──────
            node(n_cdr, "cdr_mutator", {
                "num_variants": 4,
                "seed": None,
            }, 800, 200),

            # ── 6. Structure prediction ────────────────────────────────────────
            node(n_immune, "immunebuilder", {}, 1050, 200),

            # ── 7. Docking score (RL reward) ───────────────────────────────────
            node(n_haddock, "haddock3", {
                "antigen_active_residues": (
                    "438 439 440 441 442 443 444 445 446 447 448 449 450 451 452 453 454 455 "
                    "456 457 458 459 460 461 462 463 464 465 466 467 468 469 470 471 472 473 "
                    "474 475 476 477 478 479 480 481 482 483 484 485 486 487 488 489 490 491 "
                    "492 493 494 495 496 497 498 499 500 501 502 503 504 505 506"
                ),
            }, 1300, 200),

            # ── 8. Select best variant; store score for next-iteration reward ──
            node(n_loop_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1050, 450),
        ],
        "edges": [
            # ── AbMAP state: embed VH + VL ─────────────────────────────────────
            edge(n_loop_start, "heavy_chain", n_abmap, "vh"),
            edge(n_loop_start, "light_chain", n_abmap, "vl"),

            # ── RL agent: embedding as state ───────────────────────────────────
            # reward_signals injected by loop_executor (NOT an edge — no cycle)
            edge(n_abmap, "results", n_rl, "state_embeddings"),

            # ── CDR mutator: RL-chosen action ──────────────────────────────────
            edge(n_rl, "top_cdr",         n_cdr, "cdr_target"),
            edge(n_rl, "top_strategy",    n_cdr, "strategy"),
            edge(n_rl, "top_n_mutations", n_cdr, "num_mutations"),
            edge(n_loop_start, "heavy_chain", n_cdr, "heavy_chain"),
            edge(n_loop_start, "light_chain", n_cdr, "light_chain"),

            # ── Structure prediction: variant_1 ───────────────────────────────
            edge(n_cdr, "variant_1", n_immune, "heavy_chain"),

            # ── Docking ────────────────────────────────────────────────────────
            edge(n_immune,  "structure_1", n_haddock, "antibody"),
            edge(n_target,  "target",      n_haddock, "antigen"),

            # ── Loop-end ───────────────────────────────────────────────────────
            edge(n_haddock,    "scores",             n_loop_end, "haddock_scores"),
            edge(n_rl,         "recommended_actions", n_loop_end, "rl_recommended_actions"),
            edge(n_loop_start, "heavy_chain",         n_loop_end, "seed_vh"),
            edge(n_loop_start, "light_chain",         n_loop_end, "seed_vl"),
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

        spec = DEFAULT_RL_SPEC["action"]
        n_actions = (
            len(spec["cdrs"])
            * len(spec["strategies"])
            * len(spec["n_mutations_choices"])
        )
        alg = DEFAULT_RL_SPEC["algorithm"]
        print(f"✓  Seeded: {pipeline.name!r}  ({pipeline.id})")
        print(f"   Nodes       : {len(pipeline.nodes)}")
        print(f"   Edges       : {len(pipeline.edges)}")
        print(f"   Iterations  : 10")
        print(f"   RL actions  : {n_actions}  "
              f"({len(spec['cdrs'])} CDRs × {len(spec['strategies'])} strategies × "
              f"{len(spec['n_mutations_choices'])} n_mut)")
        print(f"   RL warmup   : {alg['warmup_steps']} iters")
        print(f"   RL exploit  : starts iter {alg['warmup_steps']}")
        print(f"   Reward      : HADDOCK3 docking score (lower is better)")
        print(f"   Target      : spike RBD (edit target_input node to change)")


if __name__ == "__main__":
    asyncio.run(seed())
