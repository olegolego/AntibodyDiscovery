"""Seed a minimal fast loop pipeline for testing the continue button.

Pipeline: loop_start → cdr_mutator → loop_end
  - No GPU tools (no HADDOCK, no DNN, no ImmuneBuilder)
  - cdr_mutator runs in-process (fast, <5s per iteration)
  - loop_end picks the first valid CDR variant

Run: python scripts/seed_simple_loop_pipeline.py
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "protein_design.db"

LOOP_END_CODE = """
# Each cdr_mutator variant is a dict: {"heavy_chain": "...", "light_chain": "..."}
variants = [
    cdr_mutator_variant_1,
    cdr_mutator_variant_2,
    cdr_mutator_variant_3,
    cdr_mutator_variant_4,
    cdr_mutator_variant_5,
]
valid = [v for v in variants if v and isinstance(v, dict) and v.get("heavy_chain")]

if valid:
    # Cycle through variants across iterations
    chosen = valid[(loop_iteration or 0) % len(valid)]
    next_heavy_chain = chosen["heavy_chain"]
    next_light_chain = chosen.get("light_chain") or loop_start_light_chain or ""
else:
    next_heavy_chain = loop_start_heavy_chain or ""
    next_light_chain = loop_start_light_chain or ""

result = {
    "next_heavy_chain": next_heavy_chain,
    "next_light_chain": next_light_chain,
    "iteration_summary": {
        "iteration": loop_iteration,
        "n_variants": len(valid),
        "selected_vh_prefix": (next_heavy_chain or "")[:20],
    },
}
"""

SEED_VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFT"
    "ISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS"
)
SEED_VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGT"
    "DFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK"
)


def main() -> None:
    pipeline_id = f"simple-loop-{str(uuid.uuid4())[:8]}"
    now = datetime.now(timezone.utc).isoformat()

    pipeline = {
        "id": pipeline_id,
        "name": "Simple Loop · CDR Mutator Test",
        "nodes": [
            {
                "id": "loop_start",
                "tool": "loop_start",
                "params": {
                    "heavy_chain": SEED_VH,
                    "light_chain": SEED_VL,
                    "max_iterations": 3,
                },
                "position": {"x": 100, "y": 300},
            },
            {
                "id": "cdr_mutator",
                "tool": "cdr_mutator",
                "params": {
                    "num_variants": 5,
                    "regions": ["CDR1", "CDR2", "CDR3"],
                    "num_mutations": 2,
                },
                "position": {"x": 400, "y": 300},
            },
            {
                "id": "loop_end",
                "tool": "loop_end",
                "params": {
                    "max_iterations": 3,
                    "code": LOOP_END_CODE,
                },
                "position": {"x": 700, "y": 300},
            },
        ],
        "edges": [
            # loop_start → cdr_mutator
            {"source": "loop_start.heavy_chain", "target": "cdr_mutator.heavy_chain"},
            {"source": "loop_start.light_chain", "target": "cdr_mutator.light_chain"},
            # cdr_mutator → loop_end (makes cdr_mutator a direct parent of loop_end)
            {"source": "cdr_mutator.variant_1", "target": "loop_end.variant_1"},
            {"source": "cdr_mutator.variant_2", "target": "loop_end.variant_2"},
            {"source": "cdr_mutator.variant_3", "target": "loop_end.variant_3"},
            {"source": "cdr_mutator.variant_4", "target": "loop_end.variant_4"},
            {"source": "cdr_mutator.variant_5", "target": "loop_end.variant_5"},
            # loop_start → loop_end (makes loop_start a direct parent so its outputs are injected)
            {"source": "loop_start.heavy_chain", "target": "loop_end.loop_start_heavy_chain"},
            {"source": "loop_start.light_chain", "target": "loop_end.loop_start_light_chain"},
        ],
    }

    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO pipelines (id, name, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (pipeline_id, pipeline["name"], json.dumps(pipeline), now, now),
    )
    db.commit()
    db.close()
    print(f"Seeded pipeline: {pipeline_id}")
    print(f"Name: {pipeline['name']}")
    print("Run 3 iterations then test the continue button.")


if __name__ == "__main__":
    main()
