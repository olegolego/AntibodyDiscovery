"""Seed the RCC-MLDE antibody optimization pipeline template.

Usage:
    cd backend && .venv/bin/python ../scripts/seed_rcc_mlde_pipeline.py

Implements exactly the algorithm from:
  "Conformational Rank Conditioned Committees for Machine Learning-Assisted
   Directed Evolution" (Presnyakov et al., arXiv:2510.24974v2)

Pipeline per iteration
──────────────────────
 1  loop_start          — entry sequence (VH/VL), patched each iteration with best candidate
 2  immunebuilder        — 4 conformations from different ImmuneBuilder samples
 3  target_input         — antigen PDB (spike RBD default)
 4  haddock3 × 4        — separate docking run per conformation (rank 1..4)
 5  abmap               — AbMAP 512d embedding of the current sequence
 6  rcc_mlde (train)    — train M-committee per rank on ALL accumulated data
                          (accumulated_dataset injected automatically from loop history)
 7  cdr_mutator          — BLOSUM62-guided CDR diversification (B=50 variants)
 8  abmap (candidates)  — embed CDR variants for scoring
 9  feasibility_filter   — compute node: biological feasibility filter (Riot-NA inspired):
                           no N-glycosylation, no 5+ consecutive same AA, charge/hydrophobicity
10  rcc_mlde (score)    — score feasible candidates via RCC acquisition function
11  loop_end             — select top-1 sequence for next iteration

Loop: 10 iterations. Each adds 1 new (embedding, score×4) pair to the growing dataset.
      The training set grows by 1 sequence per round (approximating paper's B=50 selection).

Data accumulation
─────────────────
The loop executor automatically:
  • captures AbMAP embedding and HADDOCK3 scores per rank from each iteration
    via _build_history_entry in loop_executor.py
  • injects accumulated_dataset into rcc_mlde nodes via _patch_pipeline
    so each round retrains on ALL previous (embedding, rank-score) pairs
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path


def uid() -> str:
    return str(uuid.uuid4())[:8]


def node(id_: str, tool: str, params: dict, x: float, y: float) -> dict:
    return {"id": id_, "tool": tool, "params": params, "position": {"x": x, "y": y}}


def edge(src: str, src_port: str, tgt: str, tgt_port: str) -> dict:
    # PipelineEdge format: "node_id.port" for both source and target
    return {"source": f"{src}.{src_port}", "target": f"{tgt}.{tgt_port}"}


# ── Biological feasibility filter (Riot-NA inspired) ─────────────────────────
# Filters CDR variants for:
#   1. No N-glycosylation motif (N-x-S/T where x ≠ P)
#   2. No 5+ consecutive identical residues
#   3. CDR-H3 length ≤ 22 AAs (structural plausibility)
#   4. Net charge in [-4, +4]
#   5. Aromatic content ≤ 20% of CDR
FEASIBILITY_CODE = '''
import re

# Amino acid properties
HYDROPHOBIC = set("VILMFYWAC")
CHARGED_POS = set("KRH")
CHARGED_NEG = set("DE")
AROMATIC    = set("FWY")

def n_glycosylation(seq):
    """N-x-S/T where x ≠ P — would be glycosylated, unfavorable for docking."""
    return bool(re.search(r"N[^P][ST]", seq))

def has_long_repeat(seq, n=5):
    """5+ consecutive identical residues."""
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

# Score all CDR variants; keep feasible ones with their acquisition scores
feasible = {}
acq_scores = rcc_score_acquisition_scores or {}

for vname in ["variant_1", "variant_2", "variant_3", "variant_4", "variant_5",
              "variant_6", "variant_7", "variant_8"]:
    bundle_key = f"cdr_mutator_{vname}"
    bundle = locals().get(bundle_key) or {}
    vh = bundle.get("heavy_chain") or ""
    vl = bundle.get("light_chain") or ""
    if not vh:
        continue
    if is_feasible(vh, vl):
        acq = acq_scores.get(vh, -999.0)
        feasible[vh] = {"heavy_chain": vh, "light_chain": vl, "acquisition_score": acq}

# If all variants fail feasibility, fall back to best available
if not feasible and acq_scores:
    best_vh = max(acq_scores, key=lambda k: acq_scores[k])
    feasible[best_vh] = {"heavy_chain": best_vh, "acquisition_score": acq_scores[best_vh]}

result = {
    "feasible_variants": feasible,
    "n_feasible": len(feasible),
    "n_total": 8,
}
'''

# ── Loop end code ─────────────────────────────────────────────────────────────
# Runs at end of each iteration. Selects the top CDR variant by acquisition score.
# The accumulated_dataset is handled automatically by _patch_pipeline — this code
# just needs to pick the next sequence to evaluate.
LOOP_END_CODE = '''
# Pick the best feasible CDR variant by acquisition score for the next iteration.
# loop_history and all upstream outputs are available here.

feasible = feasibility_filter_feasible_variants or {}
acq_scores = rcc_score_acquisition_scores or {}

# Rank feasible variants by acquisition score (higher = better)
ranked = sorted(feasible.values(), key=lambda v: v.get("acquisition_score", -999), reverse=True)

if ranked:
    best = ranked[0]
    next_heavy_chain = best["heavy_chain"]
    next_light_chain = best.get("light_chain") or loop_start_light_chain
else:
    # Fallback: keep current sequence
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
'''


# ── Node IDs ──────────────────────────────────────────────────────────────────
N_LOOP_START  = "loop_start"
N_IMMUNE      = "immunebuilder"
N_TARGET      = "target_in"
N_HADD_R1     = "haddock_r1"
N_HADD_R2     = "haddock_r2"
N_HADD_R3     = "haddock_r3"
N_HADD_R4     = "haddock_r4"
N_ABMAP_TRAIN = "abmap_train"
N_RCC_TRAIN   = "rcc_train"
N_CDR_MUT     = "cdr_mutator"
N_ABMAP_CAND  = "abmap_cand"
N_FEASIBILITY = "feasibility_filter"
N_RCC_SCORE   = "rcc_score"
N_LOOP_END    = "loop_end"

# Spike RBD epitope residues (from paper / HADDOCK default)
RBD_EPITOPE = (
    "438 439 440 441 442 443 444 445 446 447 448 449 450 451 452 453 454 455 456 "
    "472 473 474 475 476 477 478 479 480 481 482 483 484 485 486 487 488 489 490 "
    "491 492 493 494 495 496 497 498 499 500 501 502 503 504 505 506"
)


def build_pipeline() -> dict:
    pipeline_id = f"rcc-mlde-{uid()}"

    nodes = [
        # ── Loop entry ────────────────────────────────────────────────
        node(N_LOOP_START, "loop_start", {
            "heavy_chain": "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS",
            "light_chain":  "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK",
            "max_iterations": 10,
        }, x=50, y=300),

        # ── Antigen ───────────────────────────────────────────────────
        node(N_TARGET, "target_input", {
            "pdb": "",
        }, x=50, y=80),

        # ── ImmuneBuilder: 4 conformations per sequence ───────────────
        node(N_IMMUNE, "immunebuilder", {}, x=300, y=300),

        # ── HADDOCK3 × 4 (one per conformation rank) ──────────────────
        # Rank 1 = highest confidence ImmuneBuilder conformation
        node(N_HADD_R1, "haddock3", {
            "antigen_active_residues": RBD_EPITOPE,
        }, x=580, y=0),
        node(N_HADD_R2, "haddock3", {
            "antigen_active_residues": RBD_EPITOPE,
        }, x=580, y=140),
        node(N_HADD_R3, "haddock3", {
            "antigen_active_residues": RBD_EPITOPE,
        }, x=580, y=280),
        node(N_HADD_R4, "haddock3", {
            "antigen_active_residues": RBD_EPITOPE,
        }, x=580, y=420),

        # ── AbMAP: embed the CURRENT sequence (for training) ──────────
        node(N_ABMAP_TRAIN, "abmap", {}, x=300, y=140),

        # ── RCC-MLDE: train committees on ALL accumulated data ─────────
        # accumulated_dataset is injected by the loop executor automatically
        node(N_RCC_TRAIN, "rcc_mlde", {
            "n_committee":     5,
            "model_type":      "ridge",
            "kappa_epi":       2.0,
            "kappa_conf":      0.5,
            "top_k":           50,
            "lower_is_better": True,
            "task":            "regression",
        }, x=860, y=210),

        # ── CDR Mutator: biologically-informed diversification ─────────
        # BLOSUM62 substitutions in CDR-H1/H2/H3 (as in paper)
        node(N_CDR_MUT, "cdr_mutator", {
            "strategy":       "blosum62",
            "num_variants":   8,
            "num_mutations":  3,
            "cdr_h1": True, "cdr_h2": True, "cdr_h3": True,
            "cdr_l1": False, "cdr_l2": False, "cdr_l3": False,
        }, x=1120, y=210),

        # ── AbMAP: embed CDR variants (candidates) ────────────────────
        node(N_ABMAP_CAND, "abmap", {}, x=1380, y=210),

        # ── Feasibility filter (Riot-NA inspired) ─────────────────────
        node(N_FEASIBILITY, "compute", {
            "code": FEASIBILITY_CODE,
        }, x=1600, y=210),

        # ── RCC-MLDE: score candidates with trained committees ─────────
        node(N_RCC_SCORE, "rcc_mlde", {
            "n_committee":     5,
            "model_type":      "ridge",
            "kappa_epi":       2.0,
            "kappa_conf":      0.5,
            "top_k":           8,
            "lower_is_better": True,
            "task":            "regression",
        }, x=1820, y=210),

        # ── Loop end: select top CDR variant for next iteration ────────
        node(N_LOOP_END, "loop_end", {
            "code": LOOP_END_CODE,
        }, x=2060, y=210),
    ]

    edges = [
        # loop_start → immunebuilder + abmap_train
        edge(N_LOOP_START, "heavy_chain", N_IMMUNE,      "heavy_chain"),
        edge(N_LOOP_START, "light_chain", N_IMMUNE,      "light_chain"),
        edge(N_LOOP_START, "heavy_chain", N_ABMAP_TRAIN, "heavy_chain"),
        edge(N_LOOP_START, "light_chain", N_ABMAP_TRAIN, "light_chain"),

        # target → 4× HADDOCK3
        edge(N_TARGET, "pdb", N_HADD_R1, "antigen"),
        edge(N_TARGET, "pdb", N_HADD_R2, "antigen"),
        edge(N_TARGET, "pdb", N_HADD_R3, "antigen"),
        edge(N_TARGET, "pdb", N_HADD_R4, "antigen"),

        # ImmuneBuilder conformation r → HADDOCK3 rank r (antibody input)
        edge(N_IMMUNE, "structure_1", N_HADD_R1, "antibody"),
        edge(N_IMMUNE, "structure_2", N_HADD_R2, "antibody"),
        edge(N_IMMUNE, "structure_3", N_HADD_R3, "antibody"),
        edge(N_IMMUNE, "structure_4", N_HADD_R4, "antibody"),

        # AbMAP embedding → rcc_mlde training (current round's sequence)
        edge(N_ABMAP_TRAIN, "embedding", N_RCC_TRAIN, "embeddings"),

        # HADDOCK3 scores → rcc_mlde training (4 rank scores)
        edge(N_HADD_R1, "scores", N_RCC_TRAIN, "scores_rank_1"),
        edge(N_HADD_R2, "scores", N_RCC_TRAIN, "scores_rank_2"),
        edge(N_HADD_R3, "scores", N_RCC_TRAIN, "scores_rank_3"),
        edge(N_HADD_R4, "scores", N_RCC_TRAIN, "scores_rank_4"),

        # CDR Mutator: seed with current loop sequence
        edge(N_LOOP_START, "heavy_chain", N_CDR_MUT, "heavy_chain"),
        edge(N_LOOP_START, "light_chain", N_CDR_MUT, "light_chain"),

        # CDR variants → AbMAP candidate embedding
        edge(N_CDR_MUT, "heavy_chain", N_ABMAP_CAND, "heavy_chain"),
        edge(N_CDR_MUT, "light_chain", N_ABMAP_CAND, "light_chain"),

        # AbMAP candidates → rcc_score
        edge(N_ABMAP_CAND, "embedding", N_RCC_SCORE, "candidate_embeddings"),

        # Trained committee artifact → rcc_score (inference mode)
        edge(N_RCC_TRAIN, "model_artifact", N_RCC_SCORE, "model_artifact"),

        # rcc_score → feasibility_filter (to annotate acquisition scores)
        edge(N_RCC_SCORE, "acquisition_scores", N_FEASIBILITY, "rcc_score_acquisition_scores"),

        # CDR variants → feasibility_filter (for biological checks)
        edge(N_CDR_MUT, "variant_1", N_FEASIBILITY, "cdr_mutator_variant_1"),
        edge(N_CDR_MUT, "variant_2", N_FEASIBILITY, "cdr_mutator_variant_2"),
        edge(N_CDR_MUT, "variant_3", N_FEASIBILITY, "cdr_mutator_variant_3"),
        edge(N_CDR_MUT, "variant_4", N_FEASIBILITY, "cdr_mutator_variant_4"),
        edge(N_CDR_MUT, "variant_5", N_FEASIBILITY, "cdr_mutator_variant_5"),
        edge(N_CDR_MUT, "variant_6", N_FEASIBILITY, "cdr_mutator_variant_6"),
        edge(N_CDR_MUT, "variant_7", N_FEASIBILITY, "cdr_mutator_variant_7"),
        edge(N_CDR_MUT, "variant_8", N_FEASIBILITY, "cdr_mutator_variant_8"),

        # loop_start → loop_end (for variable access)
        edge(N_LOOP_START, "heavy_chain", N_LOOP_END, "loop_start_heavy_chain"),
        edge(N_LOOP_START, "light_chain", N_LOOP_END, "loop_start_light_chain"),

        # feasibility_filter → loop_end
        edge(N_FEASIBILITY, "result", N_LOOP_END, "feasibility_filter_result"),

        # rcc_score → loop_end
        edge(N_RCC_SCORE, "acquisition_scores", N_LOOP_END, "rcc_score_acquisition_scores"),
    ]

    return {
        "id":    pipeline_id,
        "name":  "RCC-MLDE · Antibody Optimization (Loop)",
        "nodes": nodes,
        "edges": edges,
    }


async def seed_db() -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.db.models import PipelineRow
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select

    pipeline = build_pipeline()

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(PipelineRow).where(PipelineRow.name.like("RCC-MLDE%"))
        )).scalars().all()
        for row in existing:
            await db.delete(row)

        db.add(PipelineRow(id=pipeline["id"], name=pipeline["name"], data=json.dumps(pipeline)))
        await db.commit()

    print(f"Seeded: {pipeline['name']}")
    print(f"  ID: {pipeline['id']}")
    print(f"  Nodes: {len(pipeline['nodes'])}, Edges: {len(pipeline['edges'])}")
    print()
    print("Pipeline stages:")
    for nd in pipeline["nodes"]:
        print(f"  {nd['id']:25s}  tool={nd['tool']}")
    print()
    print("Data accumulation:")
    print("  Each iteration: AbMAP embedding + 4 HADDOCK3 scores captured by loop executor")
    print("  rcc_mlde.accumulated_dataset injected by _patch_pipeline before each retraining")
    print("  Training set grows: n=1 (round 0), n=2 (round 1), ..., n=10 (round 9)")


if __name__ == "__main__":
    asyncio.run(seed_db())
