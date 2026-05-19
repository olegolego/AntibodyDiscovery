"""Seed DNN test pipelines and validate architectures via the backend.

Usage:
    cd backend && python ../scripts/seed_dnn_pipelines.py

Creates several canonical DNN pipelines with diverse architectures in the
pipeline database so they're immediately available from the canvas.

Also validates that run.py can build every DynamicDNN from each architecture
spec — no actual GPU/ESM needed for this check.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Architecture specs
# ---------------------------------------------------------------------------

# Shared edge builder
def edges(*pairs: tuple[str, str]) -> list[dict]:
    return [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(pairs)]


def spec(nodes, edge_pairs) -> dict:
    return {"version": "1.0", "nodes": nodes, "edges": edges(*edge_pairs)}


def node(id_, type_, params, x=200, y=0) -> dict:
    return {"id": id_, "type": type_, "params": params, "position": {"x": x, "y": y}}


# ── 1. Simple MLP – regression (AbMAP 512d → 256 → 64 → 1) ─────────────────
ARCH_SIMPLE_MLP = spec([
    node("inp",   "Input",      {"features": 512},                                    y=50),
    node("ln1",   "Linear",     {"in_features": 512, "out_features": 256, "bias": True}, y=230),
    node("rl1",   "ReLU",       {},                                                    y=390),
    node("dp1",   "Dropout",    {"p": 0.3},                                            y=520),
    node("ln2",   "Linear",     {"in_features": 256, "out_features": 64, "bias": True}, y=660),
    node("rl2",   "ReLU",       {},                                                    y=820),
    node("out",   "Output",     {"out_features": 1, "task": "regression"},             y=960),
], [("inp","ln1"),("ln1","rl1"),("rl1","dp1"),("dp1","ln2"),("ln2","rl2"),("rl2","out")])

# ── 2. Deep MLP + BatchNorm – regression (ESM 650M 1280d) ───────────────────
ARCH_DEEP_BN = spec([
    node("inp",   "Input",      {"features": 1280},                                    y=50),
    node("ln1",   "Linear",     {"in_features": 1280, "out_features": 512, "bias": True}, y=230),
    node("bn1",   "BatchNorm1d",{"num_features": 512, "eps": 1e-5, "momentum": 0.1},   y=390),
    node("rl1",   "ReLU",       {},                                                    y=520),
    node("dp1",   "Dropout",    {"p": 0.4},                                            y=650),
    node("ln2",   "Linear",     {"in_features": 512, "out_features": 256, "bias": True}, y=790),
    node("rl2",   "GELU",       {},                                                    y=950),
    node("ln3",   "Linear",     {"in_features": 256, "out_features": 64, "bias": True}, y=1100),
    node("rl3",   "ReLU",       {},                                                    y=1250),
    node("out",   "Output",     {"out_features": 1, "task": "regression"},             y=1390),
], [("inp","ln1"),("ln1","bn1"),("bn1","rl1"),("rl1","dp1"),("dp1","ln2"),
    ("ln2","rl2"),("rl2","ln3"),("ln3","rl3"),("rl3","out")])

# ── 3. Binary classifier + LayerNorm (ESM-2 8M 320d) ────────────────────────
ARCH_BINARY_CLF = spec([
    node("inp",   "Input",      {"features": 320},                                    y=50),
    node("ln1",   "Linear",     {"in_features": 320, "out_features": 128, "bias": True}, y=230),
    node("lnorm", "LayerNorm",  {"normalized_shape": 128},                             y=390),
    node("rl1",   "GELU",       {},                                                    y=520),
    node("dp1",   "Dropout",    {"p": 0.2},                                            y=650),
    node("ln2",   "Linear",     {"in_features": 128, "out_features": 32, "bias": True}, y=790),
    node("rl2",   "GELU",       {},                                                    y=950),
    node("out",   "Output",     {"out_features": 1, "task": "binary_classification"},  y=1090),
], [("inp","ln1"),("ln1","lnorm"),("lnorm","rl1"),("rl1","dp1"),
    ("dp1","ln2"),("ln2","rl2"),("rl2","out")])

# ── 4. Multi-input: AbMAP 512d + ESM-2 8M 320d (UpstreamInput) ──────────────
# Two separate branches that merge via concatenation before the final layers.
# The adapter injects slice_start/slice_end so each UpstreamInput node
# receives its slice of the 832-dim concatenated tensor.
ARCH_MULTI_INPUT = spec([
    node("up1",   "UpstreamInput",
         {"features": 512, "port": "embedding_input",   "toolId": "abmap",         "toolName": "AbMAP"},
         x=60, y=80),
    node("up2",   "UpstreamInput",
         {"features": 320, "port": "embedding_input_2", "toolId": "esm_embedding", "toolName": "ESM2 8M"},
         x=60, y=280),
    node("ab_ln", "Linear",     {"in_features": 512, "out_features": 256, "bias": True}, x=310, y=80),
    node("ab_rl", "ReLU",       {},                                                    x=310, y=240),
    node("es_ln", "Linear",     {"in_features": 320, "out_features": 256, "bias": True}, x=310, y=280),
    node("es_rl", "ReLU",       {},                                                    x=310, y=440),
    # Merge node (512-dim after cat of two 256-dim branches)
    node("mg_ln", "Linear",     {"in_features": 512, "out_features": 128, "bias": True}, x=600, y=280),
    node("mg_rl", "ReLU",       {},                                                    x=600, y=440),
    node("dp1",   "Dropout",    {"p": 0.3},                                            x=600, y=570),
    node("out",   "Output",     {"out_features": 1, "task": "regression"},             x=600, y=710),
], [
    ("up1","ab_ln"),("ab_ln","ab_rl"),
    ("up2","es_ln"),("es_ln","es_rl"),
    # Two sources → mg_ln: DynamicDNN auto-concatenates [B,256]+[B,256]=[B,512]
    ("ab_rl","mg_ln"),("es_rl","mg_ln"),
    ("mg_ln","mg_rl"),("mg_rl","dp1"),("dp1","out"),
])

# ── 5. Residual MLP (skip connection around middle block) ───────────────────
ARCH_RESIDUAL = spec([
    node("inp",   "Input",      {"features": 512},                                    y=50),
    node("ln1",   "Linear",     {"in_features": 512, "out_features": 256, "bias": True}, y=230),
    node("rl1",   "ReLU",       {},                                                    y=390),
    # Skip branch: direct from inp to res node (needs matching 256-dim — use projection)
    node("proj",  "Linear",     {"in_features": 512, "out_features": 256, "bias": False}, y=230, x=460),
    node("res",   "Residual",   {},                                                    y=520),
    node("ln2",   "Linear",     {"in_features": 256, "out_features": 64, "bias": True}, y=680),
    node("rl2",   "ReLU",       {},                                                    y=840),
    node("out",   "Output",     {"out_features": 1, "task": "regression"},             y=980),
], [
    ("inp","ln1"),("ln1","rl1"),("rl1","res"),
    ("inp","proj"),("proj","res"),
    ("res","ln2"),("ln2","rl2"),("rl2","out"),
])

# ── 6. LSTM sequence model (per-residue ESM → LSTM → regression) ─────────────
ARCH_LSTM = spec([
    node("inp",   "Input3D",    {"features": 1280},                                    y=50),
    node("lstm",  "LSTM",       {"input_size": 1280, "hidden_size": 256, "num_layers": 2,
                                  "bidirectional": True, "dropout": 0.1, "return_last": True}, y=230),
    node("dp1",   "Dropout",    {"p": 0.2},                                            y=430),
    node("ln1",   "Linear",     {"in_features": 512, "out_features": 64, "bias": True},  y=570),
    node("rl1",   "ReLU",       {},                                                    y=730),
    node("out",   "Output",     {"out_features": 1, "task": "regression"},             y=870),
], [("inp","lstm"),("lstm","dp1"),("dp1","ln1"),("ln1","rl1"),("rl1","out")])

# ── 7. Transformer encoder (per-residue → pool → regression) ─────────────────
ARCH_TRANSFORMER = spec([
    node("inp",   "Input3D",    {"features": 640},                                    y=50),
    node("tr",    "TransformerEncoder",
         {"d_model": 640, "nhead": 8, "num_layers": 2, "dim_feedforward": 1280, "dropout": 0.1},
         y=230),
    node("gap",   "GlobalAvgPool", {},                                                 y=480),
    node("ln1",   "Linear",     {"in_features": 640, "out_features": 128, "bias": True}, y=630),
    node("rl1",   "GELU",       {},                                                    y=790),
    node("dp1",   "Dropout",    {"p": 0.1},                                            y=920),
    node("out",   "Output",     {"out_features": 1, "task": "regression"},             y=1060),
], [("inp","tr"),("tr","gap"),("gap","ln1"),("ln1","rl1"),("rl1","dp1"),("dp1","out")])


# ---------------------------------------------------------------------------
# Pipeline templates that use the above architectures
# ---------------------------------------------------------------------------

def make_pipeline(name: str, arch: dict, embed_tool: str, embed_model_size: str = "8M") -> dict:
    """Canonical pipeline: dataset → embedding → custom_dnn."""
    ds_id  = str(uuid.uuid4())[:8]
    emb_id = str(uuid.uuid4())[:8]
    dnn_id = str(uuid.uuid4())[:8]

    nodes = [
        {
            "id": f"dataset_{ds_id}", "tool": "dataset",
            "params": {"dataset_id": "", "vh_column": "heavy_chain", "vl_column": "light_chain", "label_column": ""},
            "position": {"x": 100, "y": 300},
        },
        {
            "id": f"embed_{emb_id}", "tool": embed_tool,
            "params": {"model_size": embed_model_size} if embed_tool == "esm_embedding" else {},
            "position": {"x": 450, "y": 300},
        },
        {
            "id": f"dnn_{dnn_id}", "tool": "custom_dnn",
            "params": {
                "architecture_spec": arch,
                "epochs": 50, "learning_rate": 0.001,
                "task": arch["nodes"][-1]["params"].get("task", "regression"),
                "loss_fn": "auto",
            },
            "position": {"x": 800, "y": 300},
        },
    ]
    edges = [
        # dataset.heavy_chain → embed tool
        {"source": f"dataset_{ds_id}.heavy_chain", "target": f"embed_{emb_id}.in"},
        # dataset.labels → dnn
        {"source": f"dataset_{ds_id}.labels", "target": f"dnn_{dnn_id}.labels"},
        # embed.embedding → dnn.embedding_input
        {"source": f"embed_{emb_id}.embedding", "target": f"dnn_{dnn_id}.embedding_input"},
    ]
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "schema_version": "1",
        "nodes": nodes,
        "edges": edges,
    }


def make_multi_input_pipeline(name: str, arch: dict) -> dict:
    """Pipeline with AbMAP + ESM2 feeding two UpstreamInput branches."""
    ds_id   = str(uuid.uuid4())[:8]
    abm_id  = str(uuid.uuid4())[:8]
    esm_id  = str(uuid.uuid4())[:8]
    dnn_id  = str(uuid.uuid4())[:8]

    nodes = [
        {
            "id": f"dataset_{ds_id}", "tool": "dataset",
            "params": {"dataset_id": "", "vh_column": "heavy_chain", "vl_column": "light_chain", "label_column": ""},
            "position": {"x": 100, "y": 300},
        },
        {
            "id": f"abmap_{abm_id}", "tool": "abmap",
            "params": {"chain_type": "H", "embedding_type": "fixed"},
            "position": {"x": 450, "y": 150},
        },
        {
            "id": f"esm_{esm_id}", "tool": "esm_embedding",
            "params": {"model_size": "8M", "pool_mode": "mean"},
            "position": {"x": 450, "y": 450},
        },
        {
            "id": f"dnn_{dnn_id}", "tool": "custom_dnn",
            "params": {
                "architecture_spec": arch,
                "epochs": 50, "learning_rate": 0.001,
                "task": "regression",
                "loss_fn": "auto",
            },
            "position": {"x": 800, "y": 300},
        },
    ]
    edges = [
        {"source": f"dataset_{ds_id}.heavy_chain", "target": f"abmap_{abm_id}.sequence"},
        {"source": f"dataset_{ds_id}.heavy_chain", "target": f"esm_{esm_id}.sequence"},
        {"source": f"dataset_{ds_id}.labels",      "target": f"dnn_{dnn_id}.labels"},
        {"source": f"abmap_{abm_id}.embedding",    "target": f"dnn_{dnn_id}.embedding_input"},
        {"source": f"esm_{esm_id}.embedding",      "target": f"dnn_{dnn_id}.embedding_input_2"},
    ]
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "schema_version": "1",
        "nodes": nodes,
        "edges": edges,
    }


PIPELINES = [
    make_pipeline("DNN · Simple MLP [AbMAP 512d, regression]",     ARCH_SIMPLE_MLP,   "abmap"),
    make_pipeline("DNN · Deep MLP + BN [ESM-650M 1280d, regression]", ARCH_DEEP_BN,   "esm_embedding", "650M"),
    make_pipeline("DNN · Binary classifier [ESM-8M 320d]",           ARCH_BINARY_CLF, "esm_embedding", "8M"),
    make_multi_input_pipeline("DNN · Multi-input AbMAP+ESM [parallel branches, regression]", ARCH_MULTI_INPUT),
    make_pipeline("DNN · Residual MLP [AbMAP 512d, regression]",     ARCH_RESIDUAL,   "abmap"),
    make_pipeline("DNN · Bi-LSTM [ESM-650M per-residue, regression]", ARCH_LSTM,       "esm_embedding", "650M"),
    make_pipeline("DNN · Transformer Encoder [ESM-150M per-residue, regression]", ARCH_TRANSFORMER, "esm_embedding", "150M"),
]


# ---------------------------------------------------------------------------
# Structural validation: build each DynamicDNN and verify forward() runs
# ---------------------------------------------------------------------------

def validate_architectures() -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "custom_dnn"))
    import torch
    from run import DynamicDNN

    cases = [
        ("Simple MLP",        ARCH_SIMPLE_MLP,    torch.randn(4, 512)),
        ("Deep MLP + BN",     ARCH_DEEP_BN,       torch.randn(4, 1280)),
        ("Binary classifier", ARCH_BINARY_CLF,    torch.randn(4, 320)),
        ("Residual MLP",      ARCH_RESIDUAL,      torch.randn(4, 512)),
        # LSTM / Transformer need 3D input [B, L, D]
        ("Bi-LSTM",           ARCH_LSTM,           torch.randn(4, 20, 1280)),
        ("Transformer",       ARCH_TRANSFORMER,    torch.randn(4, 20, 640)),
    ]

    # Multi-input: simulate the adapter injecting slices
    multi_spec = json.loads(json.dumps(ARCH_MULTI_INPUT))
    slice_map = {"up1": (0, 512), "up2": (512, 832)}
    for n in multi_spec["nodes"]:
        if n["type"] == "UpstreamInput" and n["id"] in slice_map:
            s, e = slice_map[n["id"]]
            n["params"]["slice_start"] = s
            n["params"]["slice_end"]   = e
    cases.append(("Multi-input (sliced)", multi_spec, torch.randn(4, 832)))

    print("\n── Architecture validation ─────────────────────────────")
    all_ok = True
    for name, arch, x in cases:
        try:
            model = DynamicDNN(arch)
            with torch.no_grad():
                out = model(x)
            n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
            print(f"  ✓  {name:35s}  input={list(x.shape)}  output={list(out.shape)}  params={n_params:,}")
        except Exception as exc:
            print(f"  ✗  {name:35s}  ERROR: {exc}")
            all_ok = False

    print("─" * 55)
    if all_ok:
        print("All architectures OK.\n")
    else:
        print("Some architectures FAILED — fix before seeding.\n")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Seed pipelines into the DB
# ---------------------------------------------------------------------------

async def seed_db() -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.db.models import PipelineRow
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        # Remove any existing DNN test pipelines from previous seeds
        existing = (await db.execute(
            select(PipelineRow).where(PipelineRow.name.like("DNN ·%"))
        )).scalars().all()
        for row in existing:
            await db.delete(row)

        for p in PIPELINES:
            row = PipelineRow(
                id=p["id"],
                name=p["name"],
                data=json.dumps(p),
            )
            db.add(row)

        await db.commit()
    print(f"Seeded {len(PIPELINES)} DNN test pipelines into the database.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true",
                        help="Only validate architectures, don't write to DB")
    parser.add_argument("--seed-only", action="store_true",
                        help="Only seed DB, skip architecture validation")
    args = parser.parse_args()

    if not args.seed_only:
        validate_architectures()

    if not args.validate_only:
        import asyncio
        asyncio.run(seed_db())
