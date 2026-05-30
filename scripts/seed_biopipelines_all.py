#!/usr/bin/env python3
"""Seed all 5 BioPipelines application pipelines.

Reference:
  Quargnali & Rivera-Fuentes, "BioPipelines: Accessible Computational Protein
  and Ligand Design for Chemical Biologists", bioRxiv 2026.
  DOI: https://doi.org/10.64898/2026.03.11.711024

Applications implemented:
  App 1 — Inverse Folding              (target_input → proteinmpnn → esmfold)
  App 2 — Domain / Backbone Redesign   (rfdiffusion → proteinmpnn → esmfold)
  App 3 — Compound Screening           (sequence_input + compound_library → boltz2)
  App 4 — FRET Sensor Linker Opt.      (fuse → esmfold)
  App 5 — Iterative Binding Optim.     (sequence_input → boltz2 → distance_selector
                                           → ligand_mpnn → boltz2)

Run:
    python scripts/seed_biopipelines_all.py
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "backend" / "protein_design.db"

# ── App 1: Inverse Folding ────────────────────────────────────────────────────
# Paper §2 Application 1:
#   "Given a target protein structure, ProteinMPNN designs sequences likely to
#    fold to that structure (inverse folding). AlphaFold2 then validates that the
#    designed sequence re-folds to the intended target geometry."
APP1 = {
    "id": "pipe-biopipelines-inverse-folding",
    "name": "BioPipelines · App 1 — Inverse Folding (target → ProteinMPNN → ESMFold)",
    "schema_version": "1",
    "nodes": [
        # Paper: user provides a target PDB structure
        # Default: SARS-CoV-2 spike RBD (loaded from tools/data/targets/spike_rbd.pdb)
        {
            "id": "target_in",
            "tool": "target_input",
            "params": {
                "target": "__default_file__:spike_rbd.pdb",
            },
            "position": {"x": 100, "y": 300},
        },
        # Paper: ProteinMPNN inverse-folds the target structure into sequences
        {
            "id": "proteinmpnn",
            "tool": "proteinmpnn",
            "params": {
                "num_sequences": 4,
                "sampling_temp": 0.1,
            },
            "position": {"x": 450, "y": 300},
        },
        # Paper: AlphaFold2 validates re-folding (ESMFold used here — same role)
        {
            "id": "esmfold",
            "tool": "esmfold",
            "params": {},
            "position": {"x": 800, "y": 300},
        },
    ],
    "edges": [
        # Paper Fig 1: "target structure → ProteinMPNN inverse folding"
        {"source": "target_in.target",      "target": "proteinmpnn.structure"},
        # Paper Fig 1: "ProteinMPNN sequence → AlphaFold2 structure validation"
        {"source": "proteinmpnn.sequence",  "target": "esmfold.sequence"},
    ],
}

# ── App 2: Domain / Backbone Redesign ─────────────────────────────────────────
# Paper §2 Application 2:
#   "RFdiffusion generates new backbone geometries … ProteinMPNN performs inverse
#    folding … AlphaFold2 validates the predicted structure."
APP2 = {
    "id": "pipe-biopipelines-backbone-design",
    "name": "BioPipelines · App 2 — Backbone Redesign (RFdiffusion → ProteinMPNN → ESMFold)",
    "schema_version": "1",
    "nodes": [
        # Paper: RFdiffusion de novo backbone generation (10 backbones, 50–70 aa LID)
        {
            "id": "rfdiffusion",
            "tool": "rfdiffusion",
            "params": {
                "num_designs": 1,
                "num_residues": 60,
                "diffusion_steps": 50,
                "target_pdb": "",
                "hotspot_residues": "",
            },
            "position": {"x": 100, "y": 300},
        },
        # Paper: ProteinMPNN generates 2 sequences per backbone
        {
            "id": "proteinmpnn",
            "tool": "proteinmpnn",
            "params": {
                "num_sequences": 2,
                "sampling_temp": 0.1,
            },
            "position": {"x": 450, "y": 300},
        },
        # Paper: AlphaFold2 structure validation (ESMFold substituted)
        {
            "id": "esmfold",
            "tool": "esmfold",
            "params": {},
            "position": {"x": 800, "y": 300},
        },
    ],
    "edges": [
        # Paper Fig 2: "RFdiffusion backbone → ProteinMPNN"
        {"source": "rfdiffusion.backbone",  "target": "proteinmpnn.structure"},
        # Paper Fig 2: "ProteinMPNN sequence → AlphaFold2"
        {"source": "proteinmpnn.sequence",  "target": "esmfold.sequence"},
    ],
}

# ── App 3: Compound Screening ─────────────────────────────────────────────────
# Paper §2 Application 3:
#   "A small-molecule library is defined and Boltz2 co-folds each compound with
#    the target protein, returning binding probability and predicted affinity."
#   Note: screening iterates boltz2 over each compound. This seed shows the
#   single-compound (first library entry) version; wrap in loop for full screen.
APP3 = {
    "id": "pipe-biopipelines-compound-screening",
    "name": "BioPipelines · App 3 — Compound Screening (library → Boltz2)",
    "schema_version": "1",
    "nodes": [
        # User provides target protein sequence (both VH and VL for full antibody)
        {
            "id": "seq_in",
            "tool": "sequence_input",
            "params": {
                # Default: trastuzumab VH/VL (HER2 binder) — swap for your target
                "heavy_chain": "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS",
                "light_chain": "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK",
            },
            "position": {"x": 100, "y": 300},
        },
        # Paper: define a compound library with SMILES strings
        {
            "id": "comp_lib",
            "tool": "compound_library",
            "params": {
                "smiles_dict": json.dumps({
                    "ibuprofen":   "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
                    "aspirin":     "CC(=O)Oc1ccccc1C(=O)O",
                    "paracetamol": "CC(=O)Nc1ccc(O)cc1",
                }),
            },
            "position": {"x": 100, "y": 500},
        },
        # Paper: Boltz2 co-folds protein + each ligand, returning binding metrics
        {
            "id": "boltz2",
            "tool": "boltz2",
            "params": {
                "ligand_name": "LIG",
            },
            "position": {"x": 450, "y": 400},
        },
    ],
    "edges": [
        # Paper Fig 3: "protein sequence → Boltz2 (VH as chain H)"
        {"source": "seq_in.heavy_chain",   "target": "boltz2.sequence"},
        # VL as chain L for full antibody co-fold
        {"source": "seq_in.light_chain",   "target": "boltz2.light_chain"},
        # Paper Fig 3: "compound library → Boltz2 (first compound SMILES)"
        {"source": "comp_lib.compounds",   "target": "boltz2.ligand_smiles"},
    ],
}

# ── App 4: FRET Sensor Linker Optimization ────────────────────────────────────
# Paper §2 Application 4:
#   "Fuse creates combinatorial linker variants between two fluorescent domains.
#    AlphaFold2 predicts each fusion structure; inter-chromophore distance is
#    measured to identify linker lengths compatible with efficient FRET."
APP4 = {
    "id": "pipe-biopipelines-fret-linker",
    "name": "BioPipelines · App 4 — FRET Linker Optimization (Fuse → ESMFold)",
    "schema_version": "1",
    "nodes": [
        # Paper: generate all (GSG)n linker variants between CFP and YFP domains
        {
            "id": "fuse",
            "tool": "fuse",
            "params": {
                # Shortened CFP and YFP sequences for illustration
                # In production: replace with full-length fluorescent protein sequences
                "sequences": json.dumps([
                    "MVSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLTYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGIT",
                    "MVSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLGYGLQCFARYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGIT",
                ]),
                "linker": "GSG",
                # Paper: linker lengths 0–5 repeats tested per junction
                "linker_lengths": json.dumps(["0-5"]),
                "name": "CFP-YFP",
            },
            "position": {"x": 100, "y": 300},
        },
        # Paper: AlphaFold2 structure prediction of each linker variant (ESMFold used here)
        {
            "id": "esmfold",
            "tool": "esmfold",
            "params": {},
            "position": {"x": 500, "y": 300},
        },
    ],
    "edges": [
        # Paper Fig 4: "fusion variants → structure prediction"
        # The esmfold adapter takes the first sequence from the fusions list
        {"source": "fuse.fusions", "target": "esmfold.sequence"},
    ],
}

# ── App 5: Iterative Binding Optimization ─────────────────────────────────────
# Paper §2 Application 5:
#   "Boltz2 predicts the protein-ligand complex structure. DistanceSelector
#    identifies binding-pocket residues within 5 Å of the ligand. LigandMPNN
#    redesigns those residues to optimize binding. Boltz2 then re-evaluates
#    binding probability of the redesigned complex."
#   Full optimization loops this sequence N times; this seed shows one iteration.
APP5 = {
    "id": "pipe-biopipelines-binding-opt",
    "name": "BioPipelines · App 5 — Iterative Binding Optimization (Boltz2 → LigandMPNN → Boltz2)",
    "schema_version": "1",
    "nodes": [
        # Paper: user provides initial protein sequence (VH + VL for antibody target)
        {
            "id": "seq_in",
            "tool": "sequence_input",
            "params": {
                "heavy_chain": "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS",
                "light_chain": "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK",
            },
            "position": {"x": 100, "y": 300},
        },
        # Paper: Boltz2 initial structure prediction with ligand
        {
            "id": "boltz2_init",
            "tool": "boltz2",
            "params": {
                # Ibuprofen as example ligand — swap for your compound
                "ligand_smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
                "ligand_name": "IBU",
            },
            "position": {"x": 450, "y": 300},
        },
        # Paper: DistanceSelector finds pocket residues within 5 Å of ligand
        {
            "id": "dist_sel",
            "tool": "distance_selector",
            "params": {
                "ligand_name": "IBU",
                "distance_cutoff": 5.0,
            },
            "position": {"x": 800, "y": 300},
        },
        # Paper: LigandMPNN redesigns pocket residues
        {
            "id": "ligand_mpnn",
            "tool": "ligand_mpnn",
            "params": {
                "num_sequences": 5,
                "sampling_temp": 0.1,
            },
            "position": {"x": 1150, "y": 300},
        },
        # Paper: Boltz2 re-evaluates binding of redesigned sequences
        {
            "id": "boltz2_eval",
            "tool": "boltz2",
            "params": {
                "ligand_smiles": "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
                "ligand_name": "IBU",
            },
            "position": {"x": 1500, "y": 300},
        },
    ],
    "edges": [
        # Paper Fig 5: "initial sequence → Boltz2 structure prediction" (VH + VL)
        {"source": "seq_in.heavy_chain",        "target": "boltz2_init.sequence"},
        {"source": "seq_in.light_chain",        "target": "boltz2_init.light_chain"},
        # Paper Fig 5: "Boltz2 structure → DistanceSelector (pocket identification)"
        {"source": "boltz2_init.structure",     "target": "dist_sel.structure"},
        # Paper Fig 5: "pocket residues → LigandMPNN (redesign)"
        {"source": "dist_sel.selections",       "target": "ligand_mpnn.redesigned"},
        # Paper Fig 5: "structure → LigandMPNN (structural context for redesign)"
        {"source": "boltz2_init.structure",     "target": "ligand_mpnn.structure"},
        # Paper Fig 5: "redesigned sequences → Boltz2 re-evaluation"
        {"source": "ligand_mpnn.sequences",     "target": "boltz2_eval.sequence"},
    ],
}


PIPELINES = [APP1, APP2, APP3, APP4, APP5]


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH} — is the backend initialised?")

    conn = sqlite3.connect(DB_PATH)
    now = datetime.now(timezone.utc).isoformat()

    for p in PIPELINES:
        conn.execute(
            "INSERT OR REPLACE INTO pipelines (id, name, data, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (p["id"], p["name"], json.dumps(p), now, now),
        )
        print(f"  ✓ {p['id']}")

    conn.commit()
    conn.close()

    print()
    print("All 5 BioPipelines application pipelines seeded.")
    print()
    print("Reference: Quargnali & Rivera-Fuentes, BioPipelines, bioRxiv 2026")
    print("  https://doi.org/10.64898/2026.03.11.711024")
    print()
    print("Pipelines:")
    for p in PIPELINES:
        print(f"  {p['id']}")
        print(f"    {p['name']}")
    print()
    print("Open the frontend → Pipelines list → load any pipeline on the canvas.")
    print()
    print("NOTE: App 3 (Compound Screening) and App 5 (Binding Opt.) require")
    print("  a running Boltz2 server — see tools/boltz2/SETUP.md.")
    print("NOTE: App 5 (Binding Opt.) also requires LigandMPNN setup:")
    print("  bash tools/ligand_mpnn/setup.sh")


if __name__ == "__main__":
    main()
