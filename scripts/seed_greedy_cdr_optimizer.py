#!/usr/bin/env python3
"""Greedy CDR Optimizer — proper multi-variant scoring, zero external dependencies.

Each iteration:
  1. CDR mutator generates 3 variants (blosum62, 2 mutations, H1+H2+H3)
  2. All 3 variants are scored independently by their own liability_scanner
  3. loop_objective picks the variant with the fewest liability motifs
  4. loop_end does greedy hill-climbing: keep if better than best seen so far

All 3 variant outputs are wired — no orphan outputs.

Node IDs and compute-node variable names
─────────────────────────────────────────
  Node ID   Tool                Variables injected into downstream compute nodes
  ────────  ──────────────────  ─────────────────────────────────────────────────────
  start     loop_start          start_heavy_chain, start_light_chain
  cdr       cdr_mutator         cdr_heavy_chain, cdr_light_chain (v1 aliases),
                                cdr_variant_1, cdr_variant_2, cdr_variant_3 (dicts)
  scan1     liability_scanner   scan1_n_liabilities, scan1_hits, scan1_summary
  scan2     liability_scanner   scan2_n_liabilities, ...
  scan3     liability_scanner   scan3_n_liabilities, ...
  obj       loop_objective      obj_objective_score, obj_n_liabilities,
                                obj_best_heavy_chain, obj_best_light_chain  (spread from result)

Usage
──────
    cd backend && .venv/bin/python ../scripts/seed_greedy_cdr_optimizer.py
    cd backend && .venv/bin/python ../scripts/test_pipeline_run.py "Greedy CDR"
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
SEED_VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGYTFTSYNMHWVRQAPGKGLEWVSYNIYPYNNVTNYADSVKGRFTISRDTSRN"
    "TAYLQMNSLRAEDTAVYYCARGYYGSSGPYYWGQGTLVTVSS"
)
SEED_VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQ"
    "PEDFATYYCQQSYSTPPTFGQGTKVEIK"
)

# ── loop_objective ─────────────────────────────────────────────────────────────
# Receives from all 3 scanners (via edges) and from cdr (for sequences).
# Variable names = {source_node_id}_{output_key}:
#   scan1_n_liabilities, scan2_n_liabilities, scan3_n_liabilities
#   cdr_heavy_chain (v1 alias, plain str), cdr_variant_2 (dict), cdr_variant_3 (dict)
OBJECTIVE_CODE = """\
# Variable names = {source_node_id}_{output_key}
# Liability counts for each variant
n1 = int(locals().get("scan1_n_liabilities") or 999)
n2 = int(locals().get("scan2_n_liabilities") or 999)
n3 = int(locals().get("scan3_n_liabilities") or 999)

# Sequences for each variant
# variant_1: use convenience alias outputs (plain strings)
v1_vh = (locals().get("cdr_heavy_chain") or "").strip()
v1_vl = (locals().get("cdr_light_chain") or "").strip()
# variant_2 and variant_3: bundled dicts {heavy_chain, light_chain}
v2 = locals().get("cdr_variant_2") or {}
v2_vh = (v2.get("heavy_chain") or "").strip() if isinstance(v2, dict) else ""
v2_vl = (v2.get("light_chain") or "").strip() if isinstance(v2, dict) else ""
v3 = locals().get("cdr_variant_3") or {}
v3_vh = (v3.get("heavy_chain") or "").strip() if isinstance(v3, dict) else ""
v3_vl = (v3.get("light_chain") or "").strip() if isinstance(v3, dict) else ""

# Pick variant with fewest liability motifs
candidates = [
    (n1, v1_vh, v1_vl, "v1"),
    (n2, v2_vh, v2_vl, "v2"),
    (n3, v3_vh, v3_vl, "v3"),
]
# Filter out variants with empty sequences (shouldn't happen, but defensive)
candidates = [(n, vh, vl, tag) for n, vh, vl, tag in candidates if vh]
if not candidates:
    candidates = [(n1, v1_vh, v1_vl, "v1")]

best_lia, best_vh, best_vl, best_tag = min(candidates, key=lambda x: x[0])

print(f"  Variant scores: v1={n1}  v2={n2}  v3={n3}  → winner={best_tag} ({best_lia} liabilities)")

objective_score = 1.0 / (1.0 + best_lia)

# Include best_heavy_chain/light_chain in result so loop_end gets them
# via obj_best_heavy_chain and obj_best_light_chain (spread by loop_objective adapter)
result = {
    "objective_score": float(objective_score),
    "n_liabilities": best_lia,
    "best_heavy_chain": best_vh,
    "best_light_chain": best_vl,
}
"""

# ── loop_end ───────────────────────────────────────────────────────────────────
# Variable names = {source_node_id}_{output_key}:
#   obj_objective_score    — fitness of best variant this iteration
#   obj_n_liabilities      — liability count of best variant (spread from result)
#   obj_best_heavy_chain   — VH of best variant (spread from result)
#   obj_best_light_chain   — VL of best variant (spread from result)
#   start_heavy_chain      — seed VH (fallback)
#   start_light_chain      — seed VL (fallback)
LOOP_END_CODE = """\
# Variable names = {source_node_id}_{output_key}
# Node IDs: obj="obj", start="start"
fitness = float(locals().get("obj_objective_score") or 0.0)
n_lia   = int(locals().get("obj_n_liabilities") or 0)

# Best variant chosen by loop_objective this iteration
cand_vh = (locals().get("obj_best_heavy_chain") or "").strip()
cand_vl = (locals().get("obj_best_light_chain") or "").strip()

# Fallback = seed from loop_start
seed_vh = (locals().get("start_heavy_chain") or "").strip()
seed_vl = (locals().get("start_light_chain") or "").strip()

if not cand_vh:
    cand_vh = seed_vh
if not cand_vl:
    cand_vl = seed_vl

# Greedy hill-climbing across iterations
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

delta = fitness - best_fitness
print(
    f"[iter {loop_iteration}]  n_lia={n_lia}  fitness={fitness:.4f}  "
    f"best={max(fitness, best_fitness):.4f}  delta={delta:+.4f}  "
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

    n_start = "start"   # → start_heavy_chain, start_light_chain
    n_cdr   = "cdr"     # → cdr_heavy_chain, cdr_light_chain, cdr_variant_1/2/3
    n_s1    = "scan1"   # → scan1_n_liabilities
    n_s2    = "scan2"   # → scan2_n_liabilities
    n_s3    = "scan3"   # → scan3_n_liabilities
    n_obj   = "obj"     # → obj_objective_score, obj_n_liabilities, obj_best_heavy/light_chain
    n_end   = "end"

    pipeline_data = {
        "id": f"greedy-cdr-opt-{uid()}",
        "name": "Greedy CDR Optimizer",
        "schema_version": "1",
        "nodes": [
            # ── 1. Loop entry ──────────────────────────────────────────────────
            node(n_start, "loop_start", {
                "heavy_chain": SEED_VH,
                "light_chain": SEED_VL,
                "max_iterations": 6,
            }, 100, 300),

            # ── 2. CDR mutator: 3 variants ─────────────────────────────────────
            # Generates variant_1, variant_2, variant_3 — ALL are wired downstream.
            node(n_cdr, "cdr_mutator", {
                "num_variants": 3,
                "strategy": "blosum62",
                "num_mutations": 2,
                "cdr_h1": True,
                "cdr_h2": True,
                "cdr_h3": True,
                "cdr_l1": False,
                "cdr_l2": False,
                "cdr_l3": False,
                "seed": None,
            }, 420, 300),

            # ── 3a. Score variant 1 ────────────────────────────────────────────
            node(n_s1, "liability_scanner", {}, 740, 100),
            # ── 3b. Score variant 2 ────────────────────────────────────────────
            node(n_s2, "liability_scanner", {}, 740, 300),
            # ── 3c. Score variant 3 ────────────────────────────────────────────
            node(n_s3, "liability_scanner", {}, 740, 500),

            # ── 4. Pick best variant ───────────────────────────────────────────
            node(n_obj, "loop_objective", {
                "code": OBJECTIVE_CODE,
            }, 1060, 300),

            # ── 5. Greedy hill-climbing ────────────────────────────────────────
            node(n_end, "loop_end", {
                "code": LOOP_END_CODE,
            }, 1060, 550),
        ],
        "edges": [
            # ── VH + VL → CDR mutator ─────────────────────────────────────────
            edge(n_start, "heavy_chain", n_cdr, "heavy_chain"),
            edge(n_start, "light_chain", n_cdr, "light_chain"),

            # ── All 3 variants → their own scorer ─────────────────────────────
            # variant_1: use plain-string aliases (heavy_chain, light_chain)
            edge(n_cdr, "heavy_chain", n_s1, "heavy_chain"),
            edge(n_cdr, "light_chain", n_s1, "light_chain"),
            # variant_2 and variant_3: use "in" port to auto-unpack the bundle dict
            # {heavy_chain, light_chain} → heavy_chain + light_chain inputs
            edge(n_cdr, "variant_2", n_s2, "in"),
            edge(n_cdr, "variant_3", n_s3, "in"),

            # ── All 3 scorer results → loop_objective ─────────────────────────
            # (compute node — target port names are ignored; vars = scan1_*, scan2_*, scan3_*)
            edge(n_s1, "n_liabilities", n_obj, "s1"),
            edge(n_s2, "n_liabilities", n_obj, "s2"),
            edge(n_s3, "n_liabilities", n_obj, "s3"),
            # Also wire cdr → obj so variant sequences are available
            # (all cdr outputs become cdr_heavy_chain, cdr_variant_2, cdr_variant_3, etc.)
            edge(n_cdr, "heavy_chain",  n_obj, "cdr"),

            # ── loop_objective + seed → loop_end ──────────────────────────────
            # obj_objective_score, obj_best_heavy_chain, obj_best_light_chain via result spread
            edge(n_obj,   "objective_score", n_end, "score"),
            edge(n_start, "heavy_chain",     n_end, "seed_vh"),
            edge(n_start, "light_chain",     n_end, "seed_vl"),
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

    print(f"✓  Seeded: {pipeline.name!r}  ({pipeline.id})")
    print(f"   Nodes      : {len(pipeline_data['nodes'])}")
    print(f"   Edges      : {len(pipeline_data['edges'])}")
    print(f"   Iterations : 6")
    print(f"   Variants   : 3 (all scored — scan1, scan2, scan3)")
    print(f"   Strategy   : blosum62 · 2 mutations · H1+H2+H3")
    print(f"   Selection  : best variant per iter → greedy hill-climbing across iters")


if __name__ == "__main__":
    asyncio.run(seed())
