#!/usr/bin/env python3
"""Conservative CDR Screen — 2 variants per iteration, both scored, best selected.

Design rationale
─────────────────
Conservative mutations stay within biochemically similar AA groups, making them
the least likely strategy to introduce new liability motifs (NxT glycosylation,
NG/NS deamidation, DP cleavage, etc.).  Two independent variants are generated
each iteration; both are scored; the winner advances.

Node graph (single connected component — no isolated clusters)
──────────────────────────────────────────────────────────────
           ┌──────────────────────────────────────┐
  start ──►│ cdr (mutator)                        │
           │  variant_1 aliases ──► s1 (scanner)  │
           │  variant_2       ──► s2 (scanner)  │
           └──────────────────────────────────────┘
                    │s1 + s2 + cdr seqs
                    ▼
                 obj (loop_objective — picks best)
                    │ + start (seed fallback)
                    ▼
                 end (loop_end — greedy hill-climbing)

Compute-node variable names  →  {source_node_id}_{output_key}
──────────────────────────────────────────────────────────────
  In loop_objective ("obj"):
    s1_n_liabilities     from node "s1"  output "n_liabilities"
    s2_n_liabilities     from node "s2"  output "n_liabilities"
    cdr_heavy_chain      from node "cdr" output "heavy_chain"  (variant_1 alias, str)
    cdr_light_chain      from node "cdr" output "light_chain"  (variant_1 alias, str)
    cdr_variant_2        from node "cdr" output "variant_2"    (dict)

  In loop_end ("end"):
    obj_objective_score  from node "obj" output "objective_score"
    obj_n_liabilities    from node "obj" result spread "n_liabilities"
    obj_best_heavy_chain from node "obj" result spread "best_heavy_chain"
    obj_best_light_chain from node "obj" result spread "best_light_chain"
    start_heavy_chain    from node "start" output "heavy_chain"
    start_light_chain    from node "start" output "light_chain"

Usage
──────
    cd backend && .venv/bin/python ../scripts/seed_conservative_cdr_screen.py
    cd backend && .venv/bin/python ../scripts/test_pipeline_run.py "Conservative CDR"
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


def edge(src_node: str, src_port: str, tgt_node: str, tgt_port: str) -> dict:
    return {"source": f"{src_node}.{src_port}", "target": f"{tgt_node}.{tgt_port}"}


# ── Seed sequences ─────────────────────────────────────────────────────────────
SEED_VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGYTFTSYNMHWVRQAPGKGLEWVSYNIYPYNNVTNYADSVKGRFTISRDTSRN"
    "TAYLQMNSLRAEDTAVYYCARGYYGSSGPYYWGQGTLVTVSS"
)
SEED_VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQ"
    "PEDFATYYCQQSYSTPPTFGQGTKVEIK"
)

# ── loop_objective code ────────────────────────────────────────────────────────
# Variable names = {source_node_id}_{output_key}  (target port in edge is IGNORED)
# Nodes contributing here: s1, s2, cdr
OBJECTIVE_CODE = """\
# Variable names = {source_node_id}_{output_key}
# s1_n_liabilities : node "s1"  → output "n_liabilities"
# s2_n_liabilities : node "s2"  → output "n_liabilities"
# cdr_heavy_chain  : node "cdr" → output "heavy_chain"  (variant_1 plain-string alias)
# cdr_light_chain  : node "cdr" → output "light_chain"  (variant_1 plain-string alias)
# cdr_variant_2    : node "cdr" → output "variant_2"    ({heavy_chain, light_chain} dict)

n1 = int(locals().get("s1_n_liabilities") or 999)
n2 = int(locals().get("s2_n_liabilities") or 999)

v1_vh = (locals().get("cdr_heavy_chain") or "").strip()
v1_vl = (locals().get("cdr_light_chain") or "").strip()

v2_raw = locals().get("cdr_variant_2") or {}
v2_vh  = (v2_raw.get("heavy_chain") or "").strip() if isinstance(v2_raw, dict) else ""
v2_vl  = (v2_raw.get("light_chain") or "").strip() if isinstance(v2_raw, dict) else ""

candidates = [(n, vh, vl, tag)
              for n, vh, vl, tag in [(n1, v1_vh, v1_vl, "v1"), (n2, v2_vh, v2_vl, "v2")]
              if vh]
if not candidates:
    candidates = [(n1, v1_vh, v1_vl, "v1")]

best_lia, best_vh, best_vl, winner = min(candidates, key=lambda x: x[0])

print(f"  v1={n1} liab  v2={n2} liab  winner={winner} ({best_lia} liabilities)")

result = {
    "objective_score":  float(1.0 / (1.0 + best_lia)),
    "n_liabilities":    best_lia,
    "best_heavy_chain": best_vh,
    "best_light_chain": best_vl,
}
"""

# ── loop_end code ──────────────────────────────────────────────────────────────
# Variable names = {source_node_id}_{output_key}  (target port in edge is IGNORED)
# Nodes contributing here: obj, start
LOOP_END_CODE = """\
# Variable names = {source_node_id}_{output_key}
# obj_objective_score  : node "obj" → output "objective_score"
# obj_n_liabilities    : node "obj" → result spread "n_liabilities"
# obj_best_heavy_chain : node "obj" → result spread "best_heavy_chain"
# obj_best_light_chain : node "obj" → result spread "best_light_chain"
# start_heavy_chain    : node "start" → output "heavy_chain"
# start_light_chain    : node "start" → output "light_chain"

fitness = float(locals().get("obj_objective_score") or 0.0)
n_lia   = int(locals().get("obj_n_liabilities") or 0)

cand_vh = (locals().get("obj_best_heavy_chain") or "").strip()
cand_vl = (locals().get("obj_best_light_chain") or "").strip()
seed_vh = (locals().get("start_heavy_chain") or "").strip()
seed_vl = (locals().get("start_light_chain") or "").strip()

if not cand_vh:
    cand_vh = seed_vh
if not cand_vl:
    cand_vl = seed_vl

best_fitness = -999.0
best_vh = seed_vh
best_vl = seed_vl
for h in (loop_history or []):
    h_fit = float(h.get("fitness", -999.0))
    if h_fit > best_fitness:
        best_fitness = h_fit
        best_vh = h.get("vh", seed_vh) or seed_vh
        best_vl = h.get("vl", seed_vl) or seed_vl

improved         = fitness >= best_fitness
next_heavy_chain = cand_vh if improved else best_vh
next_light_chain = cand_vl if improved else best_vl

print(
    f"[iter {loop_iteration}]  n_lia={n_lia}  "
    f"fitness={fitness:.4f}  best={max(fitness, best_fitness):.4f}  "
    f"delta={fitness - best_fitness:+.4f}  "
    f"({'ACCEPTED' if improved else 'REVERTED'})"
)

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    "fitness":          fitness,
    "vh":               cand_vh,
    "vl":               cand_vl,
}
"""


async def seed() -> None:
    from app.db.session import AsyncSessionLocal
    from app.models.pipeline import Pipeline

    # ── Node IDs — these determine variable names in all compute-node code ─────
    n_start = "start"   # vars downstream: start_heavy_chain, start_light_chain
    n_cdr   = "cdr"     # vars downstream: cdr_heavy_chain, cdr_light_chain, cdr_variant_2
    n_s1    = "s1"      # vars downstream: s1_n_liabilities
    n_s2    = "s2"      # vars downstream: s2_n_liabilities
    n_obj   = "obj"     # vars downstream: obj_objective_score, obj_n_liabilities,
    #                                        obj_best_heavy_chain, obj_best_light_chain
    n_end   = "end"     # terminal — no downstream

    pipeline_data = {
        "id":             f"conservative-cdr-screen-{uid()}",
        "name":           "Conservative CDR Screen",
        "schema_version": "1",
        "nodes": [
            # ── 1. Loop entry — VH + VL ───────────────────────────────────────
            node(n_start, "loop_start", {
                "heavy_chain":  SEED_VH,
                "light_chain":  SEED_VL,
                "max_iterations": 6,
            }, 100, 300),

            # ── 2. CDR mutator — 2 variants, conservative, H2+H3, 1 mutation ──
            # num_variants=2 → variant_1 and variant_2 are BOTH wired downstream.
            # conservative strategy: stays within biochemical groups → fewest
            # new liability motifs introduced vs blosum62 or random.
            node(n_cdr, "cdr_mutator", {
                "num_variants":  2,
                "strategy":      "conservative",
                "num_mutations": 1,
                "cdr_h1":        False,
                "cdr_h2":        True,
                "cdr_h3":        True,
                "cdr_l1":        False,
                "cdr_l2":        False,
                "cdr_l3":        False,
                "seed":          None,
            }, 420, 300),

            # ── 3a. Score variant 1 ────────────────────────────────────────────
            # Receives variant_1 via cdr.heavy_chain + cdr.light_chain (plain-string aliases)
            node(n_s1, "liability_scanner", {}, 740, 140),

            # ── 3b. Score variant 2 ────────────────────────────────────────────
            # Receives variant_2 via "in" port — auto-unpacks {heavy_chain, light_chain} dict
            node(n_s2, "liability_scanner", {}, 740, 460),

            # ── 4. Pick best variant ───────────────────────────────────────────
            node(n_obj, "loop_objective", {
                "code": OBJECTIVE_CODE,
            }, 1060, 300),

            # ── 5. Greedy hill-climbing across iterations ──────────────────────
            node(n_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1380, 300),
        ],
        "edges": [
            # ── start → cdr: provide seed sequences to mutate ─────────────────
            edge(n_start, "heavy_chain", n_cdr, "heavy_chain"),
            edge(n_start, "light_chain", n_cdr, "light_chain"),

            # ── cdr → s1: variant_1 via plain-string alias outputs ─────────────
            # "heavy_chain" and "light_chain" on cdr are string aliases for variant_1
            edge(n_cdr, "heavy_chain", n_s1, "heavy_chain"),
            edge(n_cdr, "light_chain", n_s1, "light_chain"),

            # ── cdr → s2: variant_2 via "in" port (auto-unpacks the dict) ──────
            # variant_2 = {"heavy_chain": str, "light_chain": str}
            # target port "in" + dict value → inputs.update({"heavy_chain":…, "light_chain":…})
            edge(n_cdr, "variant_2", n_s2, "in"),

            # ── s1, s2, cdr → obj: scores + sequences for best-of-2 selection ──
            # loop_objective is a compute node: injects {node_id}_{key} for ALL
            # outputs of each upstream node. Target port names are ignored.
            edge(n_s1, "n_liabilities", n_obj, "s1_score"),   # → s1_n_liabilities
            edge(n_s2, "n_liabilities", n_obj, "s2_score"),   # → s2_n_liabilities
            edge(n_cdr, "heavy_chain",  n_obj, "cdr_seqs"),   # → cdr_heavy_chain, cdr_variant_2, …

            # ── obj → end: best variant fitness + sequences ────────────────────
            # obj result dict is spread by adapter → obj_best_heavy_chain etc.
            edge(n_obj,   "objective_score", n_end, "score"),    # → obj_objective_score, obj_best_*
            # seed fallback so loop_end always has a valid VH/VL if cand is empty
            edge(n_start, "heavy_chain",     n_end, "seed_vh"),  # → start_heavy_chain
            edge(n_start, "light_chain",     n_end, "seed_vl"),  # → start_light_chain
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

    n_nodes = len(pipeline_data["nodes"])
    n_edges = len(pipeline_data["edges"])
    print(f"✓  Seeded: {pipeline.name!r}  ({pipeline.id})")
    print(f"   Nodes      : {n_nodes}")
    print(f"   Edges      : {n_edges}")
    print(f"   Iterations : 6")
    print(f"   Variants   : 2  (both scored — s1 + s2)")
    print(f"   Strategy   : conservative · 1 mutation · CDR H2+H3")
    print(f"   Selection  : best(v1,v2) per iter → greedy across iters")
    print()
    print("─" * 60)
    print("loop_objective code (review variable names before running):")
    print("─" * 60)
    print(OBJECTIVE_CODE)
    print("─" * 60)
    print("loop_end code:")
    print("─" * 60)
    print(LOOP_END_CODE)
    print("─" * 60)
    print()

    # ── Connectivity self-check ────────────────────────────────────────────────
    from collections import defaultdict, deque
    node_ids = [n["id"] for n in pipeline_data["nodes"]]
    adj: dict[str, set] = defaultdict(set)
    for e in pipeline_data["edges"]:
        s, t = e["source"].split(".")[0], e["target"].split(".")[0]
        adj[s].add(t); adj[t].add(s)   # undirected
    visited: set = set()
    q = deque([node_ids[0]])
    while q:
        n = q.popleft()
        if n in visited: continue
        visited.add(n)
        q.extend(adj[n] - visited)
    if visited == set(node_ids):
        print(f"   Connectivity: ✓ all {n_nodes} nodes in one connected graph")
    else:
        isolated = set(node_ids) - visited
        print(f"   Connectivity: ✗ isolated nodes: {isolated}")

    # ── DAG self-check ────────────────────────────────────────────────────────
    in_deg: dict[str, int] = {n: 0 for n in node_ids}
    fwd: dict[str, list] = defaultdict(list)
    seen: set = set()
    for e in pipeline_data["edges"]:
        s, t = e["source"].split(".")[0], e["target"].split(".")[0]
        if (s, t) not in seen:
            seen.add((s, t)); fwd[s].append(t); in_deg[t] += 1
    q2: deque = deque(n for n, d in in_deg.items() if d == 0)
    order: list = []
    while q2:
        n = q2.popleft(); order.append(n)
        for nb in fwd[n]: in_deg[nb] -= 1; (q2.append(nb) if in_deg[nb] == 0 else None)
    if len(order) == len(node_ids):
        print(f"   DAG order  : ✓ {' → '.join(order)}")
    else:
        print(f"   DAG order  : ✗ CYCLE DETECTED — {set(node_ids)-set(order)}")


if __name__ == "__main__":
    asyncio.run(seed())
