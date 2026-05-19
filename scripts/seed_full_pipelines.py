"""Seed 10 full antibody-design pipelines (sequence → modeling → embedding → DNN).

Usage:
    cd backend && python ../scripts/seed_full_pipelines.py [--validate-only] [--seed-only]

Validates every DynamicDNN architecture with a forward pass before writing to DB.

Pipeline inventory
──────────────────
 1  Dual-Embedding Affinity          — AbMAP 512d + ESM-8M 320d → multi-branch DNN (regression)
 2  Liability-Aware Developability   — Liability + DeepSP + NetSolP + ESM → DNN (binary)
 3  Humanization Retention           — BioPhi → ESM → DNN (predict affinity after humanization)
 4  IgLM Variant Screening           — IgLM CDR redesign → AbMAP → DNN (rank generated variants)
 5  ProGen2 De-novo + Scoring        — ProGen2 generation → CHEAP + AbLang → DNN (multi-modal)
 6  CDR Saturation + DNN Filter      — CDR Mutator → AbMAP → DNN (select best mutants)
 7  Structure → Docking → Score      — ImmuneBuilder + target → HADDOCK3 → AbMAP → DNN
 8  Solubility / Stability Panel     — dataset → NetSolP + ESM-150M → DNN (solubility regression)
 9  RFdiffusion Full Discovery       — target → RFdiffusion → ProteinMPNN → ImmuneBuilder → AbMAP → DNN
10  AbLang + CHEAP Multi-Modal       — dataset → AbLang + CHEAP → DNN (parallel 512d+64d branches)
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


# ── Helpers ──────────────────────────────────────────────────────────────────

def uid() -> str:
    return str(uuid.uuid4())[:8]

def n(id_: str, tool: str, params: dict, x: float, y: float) -> dict:
    return {"id": id_, "tool": tool, "params": params, "position": {"x": x, "y": y}}

def e(src: str, tgt: str) -> dict:
    return {"source": src, "target": tgt}

def arch_node(id_: str, type_: str, params: dict, x: float = 200, y: float = 0) -> dict:
    return {"id": id_, "type": type_, "params": params, "position": {"x": x, "y": y}}

def spec(nodes: list, edge_pairs: list) -> dict:
    return {
        "version": "1.0",
        "nodes": nodes,
        "edges": [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(edge_pairs)],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Architecture specs  (DynamicDNN validated below via forward pass)
# ═══════════════════════════════════════════════════════════════════════════

# ── 1. Dual-embedding affinity ─────────────────────────────────────────────
# AbMAP 512d (port=embedding_input) + ESM-8M 320d (port=embedding_input_2)
# Two separate projection branches → concat → shared head
ARCH_DUAL_EMB = spec([
    arch_node("up_abmap", "UpstreamInput",
              {"features": 512, "port": "embedding_input",   "toolId": "abmap",         "toolName": "AbMAP"},
              x=60,  y=80),
    arch_node("up_esm",   "UpstreamInput",
              {"features": 320, "port": "embedding_input_2", "toolId": "esm_embedding", "toolName": "ESM-8M"},
              x=60,  y=280),
    arch_node("ln_abmap", "Linear",  {"in_features": 512, "out_features": 256, "bias": True}, x=320, y=80),
    arch_node("rl_abmap", "ReLU",    {}, x=320, y=240),
    arch_node("ln_esm",   "Linear",  {"in_features": 320, "out_features": 256, "bias": True}, x=320, y=280),
    arch_node("rl_esm",   "ReLU",    {}, x=320, y=440),
    # concat([B,256]+[B,256]) = [B,512]
    arch_node("ln_merge", "Linear",  {"in_features": 512, "out_features": 128, "bias": True}, x=600, y=260),
    arch_node("bn_merge", "BatchNorm1d", {"num_features": 128, "eps": 1e-5, "momentum": 0.1}, x=600, y=420),
    arch_node("rl_merge", "ReLU",    {}, x=600, y=560),
    arch_node("dp",       "Dropout", {"p": 0.3}, x=600, y=690),
    arch_node("ln_out",   "Linear",  {"in_features": 128, "out_features": 32, "bias": True}, x=600, y=820),
    arch_node("rl_out",   "ReLU",    {}, x=600, y=960),
    arch_node("out",      "Output",  {"out_features": 1, "task": "regression"}, x=600, y=1100),
], [
    ("up_abmap","ln_abmap"), ("ln_abmap","rl_abmap"),
    ("up_esm","ln_esm"),     ("ln_esm","rl_esm"),
    ("rl_abmap","ln_merge"), ("rl_esm","ln_merge"),   # auto-concat in DynamicDNN
    ("ln_merge","bn_merge"), ("bn_merge","rl_merge"),
    ("rl_merge","dp"), ("dp","ln_out"), ("ln_out","rl_out"), ("rl_out","out"),
])

# ── 2. Developability binary classifier ────────────────────────────────────
# Input from ESM-8M 320d only; binary = developable / non-developable
ARCH_DEV_BINARY = spec([
    arch_node("inp",  "Input",   {"features": 320}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 320, "out_features": 256, "bias": True}, y=220),
    arch_node("ln1n", "LayerNorm", {"normalized_shape": 256}, y=380),
    arch_node("rl1",  "GELU",    {}, y=510),
    arch_node("dp1",  "Dropout", {"p": 0.25}, y=640),
    arch_node("ln2",  "Linear",  {"in_features": 256, "out_features": 64, "bias": True}, y=780),
    arch_node("rl2",  "GELU",    {}, y=940),
    arch_node("out",  "Output",  {"out_features": 1, "task": "binary_classification"}, y=1080),
], [("inp","ln1"),("ln1","ln1n"),("ln1n","rl1"),("rl1","dp1"),
    ("dp1","ln2"),("ln2","rl2"),("rl2","out")])

# ── 3. Post-humanization affinity retention ────────────────────────────────
# ESM-8M of *humanized* sequence → predict Δ affinity (regression)
ARCH_HUMANIZATION = spec([
    arch_node("inp",  "Input",   {"features": 320}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 320, "out_features": 128, "bias": True}, y=220),
    arch_node("rl1",  "ReLU",    {}, y=380),
    arch_node("dp1",  "Dropout", {"p": 0.2}, y=510),
    arch_node("ln2",  "Linear",  {"in_features": 128, "out_features": 32, "bias": True}, y=650),
    arch_node("rl2",  "ReLU",    {}, y=810),
    arch_node("out",  "Output",  {"out_features": 1, "task": "regression"}, y=950),
], [("inp","ln1"),("ln1","rl1"),("rl1","dp1"),("dp1","ln2"),("ln2","rl2"),("rl2","out")])

# ── 4. IgLM-generated variant scoring ─────────────────────────────────────
# AbMAP 512d → MLP → affinity score
ARCH_VARIANT_SCORE = spec([
    arch_node("inp",  "Input",   {"features": 512}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 512, "out_features": 256, "bias": True}, y=220),
    arch_node("rl1",  "ReLU",    {}, y=380),
    arch_node("dp1",  "Dropout", {"p": 0.3}, y=510),
    arch_node("ln2",  "Linear",  {"in_features": 256, "out_features": 64, "bias": True}, y=650),
    arch_node("rl2",  "ReLU",    {}, y=810),
    arch_node("out",  "Output",  {"out_features": 1, "task": "regression"}, y=950),
], [("inp","ln1"),("ln1","rl1"),("rl1","dp1"),("dp1","ln2"),("ln2","rl2"),("rl2","out")])

# ── 5. ProGen2 multi-modal: CHEAP 64d + AbLang 512d → concat 576d ─────────
ARCH_PROGEN_MULTIMODAL = spec([
    arch_node("up_cheap", "UpstreamInput",
              {"features": 64,  "port": "embedding_input",   "toolId": "cheap_embedding", "toolName": "CHEAP"},
              x=60, y=80),
    arch_node("up_abla",  "UpstreamInput",
              {"features": 512, "port": "embedding_input_2", "toolId": "ablang",          "toolName": "AbLang"},
              x=60, y=260),
    arch_node("ln_c",  "Linear", {"in_features": 64,  "out_features": 128, "bias": True}, x=310, y=80),
    arch_node("rl_c",  "ReLU",   {}, x=310, y=240),
    arch_node("ln_a",  "Linear", {"in_features": 512, "out_features": 128, "bias": True}, x=310, y=260),
    arch_node("rl_a",  "ReLU",   {}, x=310, y=420),
    # concat([B,128]+[B,128]) = [B,256]
    arch_node("ln_m",  "Linear", {"in_features": 256, "out_features": 64,  "bias": True}, x=580, y=250),
    arch_node("rl_m",  "ReLU",   {}, x=580, y=410),
    arch_node("dp",    "Dropout",{"p": 0.2}, x=580, y=540),
    arch_node("out",   "Output", {"out_features": 1, "task": "regression"}, x=580, y=680),
], [
    ("up_cheap","ln_c"),("ln_c","rl_c"),
    ("up_abla","ln_a"), ("ln_a","rl_a"),
    ("rl_c","ln_m"),("rl_a","ln_m"),
    ("ln_m","rl_m"),("rl_m","dp"),("dp","out"),
])

# ── 6. CDR mutant filtering ────────────────────────────────────────────────
# Same MLP as variant scoring — AbMAP 512d
ARCH_CDR_FILTER = spec([
    arch_node("inp",  "Input",   {"features": 512}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 512, "out_features": 128, "bias": True}, y=220),
    arch_node("bn1",  "BatchNorm1d", {"num_features": 128, "eps": 1e-5, "momentum": 0.1}, y=380),
    arch_node("rl1",  "ReLU",    {}, y=510),
    arch_node("dp1",  "Dropout", {"p": 0.25}, y=640),
    arch_node("out",  "Output",  {"out_features": 1, "task": "regression"}, y=790),
], [("inp","ln1"),("ln1","bn1"),("bn1","rl1"),("rl1","dp1"),("dp1","out")])

# ── 7. Docking-informed scoring ────────────────────────────────────────────
# AbMAP 512d (structure-aware embedding of best complex sequence) → DNN
ARCH_DOCKING = spec([
    arch_node("inp",  "Input",   {"features": 512}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 512, "out_features": 256, "bias": True}, y=220),
    arch_node("rl1",  "ReLU",    {}, y=380),
    arch_node("ln2",  "Linear",  {"in_features": 256, "out_features": 64,  "bias": True}, y=520),
    arch_node("rl2",  "ReLU",    {}, y=680),
    arch_node("dp",   "Dropout", {"p": 0.2}, y=820),
    arch_node("out",  "Output",  {"out_features": 1, "task": "regression"}, y=960),
], [("inp","ln1"),("ln1","rl1"),("rl1","ln2"),("ln2","rl2"),("rl2","dp"),("dp","out")])

# ── 8. Solubility regression (ESM-150M 640d) ──────────────────────────────
ARCH_SOLUBILITY = spec([
    arch_node("inp",  "Input",   {"features": 640}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 640, "out_features": 256, "bias": True}, y=220),
    arch_node("ln1n", "LayerNorm", {"normalized_shape": 256}, y=380),
    arch_node("rl1",  "GELU",    {}, y=510),
    arch_node("dp1",  "Dropout", {"p": 0.2}, y=640),
    arch_node("ln2",  "Linear",  {"in_features": 256, "out_features": 64,  "bias": True}, y=780),
    arch_node("rl2",  "GELU",    {}, y=940),
    arch_node("out",  "Output",  {"out_features": 1, "task": "regression"}, y=1080),
], [("inp","ln1"),("ln1","ln1n"),("ln1n","rl1"),("rl1","dp1"),
    ("dp1","ln2"),("ln2","rl2"),("rl2","out")])

# ── 9. RFdiffusion de-novo discovery scoring ──────────────────────────────
# AbMAP 512d of ProteinMPNN-designed sequences → score/rank designs
ARCH_DISCOVERY = spec([
    arch_node("inp",  "Input",   {"features": 512}, y=50),
    arch_node("ln1",  "Linear",  {"in_features": 512, "out_features": 256, "bias": True}, y=220),
    arch_node("rl1",  "ReLU",    {}, y=380),
    arch_node("dp1",  "Dropout", {"p": 0.3}, y=510),
    arch_node("ln2",  "Linear",  {"in_features": 256, "out_features": 128, "bias": True}, y=650),
    arch_node("rl2",  "ReLU",    {}, y=810),
    arch_node("dp2",  "Dropout", {"p": 0.1}, y=950),
    arch_node("ln3",  "Linear",  {"in_features": 128, "out_features": 32,  "bias": True}, y=1090),
    arch_node("rl3",  "ReLU",    {}, y=1250),
    arch_node("out",  "Output",  {"out_features": 1, "task": "regression"}, y=1390),
], [("inp","ln1"),("ln1","rl1"),("rl1","dp1"),("dp1","ln2"),("ln2","rl2"),
    ("rl2","dp2"),("dp2","ln3"),("ln3","rl3"),("rl3","out")])

# ── 10. AbLang + CHEAP → deep multi-modal ──────────────────────────────────
# AbLang 512d (port=embedding_input) + CHEAP 64d (port=embedding_input_2)
ARCH_ABLANG_CHEAP = spec([
    arch_node("up_al",  "UpstreamInput",
              {"features": 512, "port": "embedding_input",   "toolId": "ablang",          "toolName": "AbLang"},
              x=60, y=80),
    arch_node("up_ch",  "UpstreamInput",
              {"features": 64,  "port": "embedding_input_2", "toolId": "cheap_embedding", "toolName": "CHEAP"},
              x=60, y=280),
    arch_node("ln_al",  "Linear", {"in_features": 512, "out_features": 256, "bias": True}, x=320, y=80),
    arch_node("bn_al",  "BatchNorm1d", {"num_features": 256, "eps": 1e-5, "momentum": 0.1}, x=320, y=240),
    arch_node("rl_al",  "GELU",   {}, x=320, y=380),
    arch_node("ln_ch",  "Linear", {"in_features": 64,  "out_features": 64,  "bias": True}, x=320, y=280),
    arch_node("rl_ch",  "GELU",   {}, x=320, y=440),
    # concat([B,256]+[B,64]) = [B,320]
    arch_node("ln_mg",  "Linear", {"in_features": 320, "out_features": 128, "bias": True}, x=600, y=280),
    arch_node("rl_mg",  "ReLU",   {}, x=600, y=440),
    arch_node("dp",     "Dropout",{"p": 0.25}, x=600, y=570),
    arch_node("ln_out", "Linear", {"in_features": 128, "out_features": 32,  "bias": True}, x=600, y=700),
    arch_node("rl_out", "ReLU",   {}, x=600, y=860),
    arch_node("out",    "Output", {"out_features": 1, "task": "regression"}, x=600, y=1000),
], [
    ("up_al","ln_al"),("ln_al","bn_al"),("bn_al","rl_al"),
    ("up_ch","ln_ch"),("ln_ch","rl_ch"),
    ("rl_al","ln_mg"),("rl_ch","ln_mg"),
    ("ln_mg","rl_mg"),("rl_mg","dp"),("dp","ln_out"),("ln_out","rl_out"),("rl_out","out"),
])


# ═══════════════════════════════════════════════════════════════════════════
# Full pipeline graph definitions
# ═══════════════════════════════════════════════════════════════════════════

def pipeline(name: str, nodes: list, edges: list) -> dict:
    return {"id": uid(), "name": name, "schema_version": "1",
            "nodes": nodes, "edges": edges}


# ── 1. Dual-Embedding Affinity Predictor ───────────────────────────────────
def p1_dual_embedding_affinity():
    ds, abm, esm, dnn = uid(), uid(), uid(), uid()
    return pipeline(
        "Full · Dual Embedding Affinity [AbMAP+ESM → multi-branch DNN]",
        nodes=[
            n(f"dataset_{ds}",  "dataset",       {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 300),
            n(f"abmap_{abm}",   "abmap",          {"chain_type":"H","task":"embed","embedding_type":"fixed"},  450, 160),
            n(f"esm_{esm}",     "esm_embedding",  {"model_size":"8M","pool_mode":"mean"},                       450, 440),
            n(f"dnn_{dnn}",     "custom_dnn",     {"architecture_spec":ARCH_DUAL_EMB,"epochs":60,"learning_rate":0.001,"task":"regression","loss_fn":"auto"}, 820, 300),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",  f"abmap_{abm}.sequence"),
            e(f"dataset_{ds}.heavy_chain",  f"esm_{esm}.sequence"),
            e(f"dataset_{ds}.labels",       f"dnn_{dnn}.labels"),
            e(f"abmap_{abm}.embedding",     f"dnn_{dnn}.embedding_input"),
            e(f"esm_{esm}.embedding",       f"dnn_{dnn}.embedding_input_2"),
        ],
    )


# ── 2. Liability-Aware Developability Classifier ───────────────────────────
# liability_scanner + deepsp + netsolp run in parallel → compute (merge flags) → ESM → DNN
def p2_developability():
    ds, lia, dsp, nsp, esm, cmp, dnn = uid(), uid(), uid(), uid(), uid(), uid(), uid()
    return pipeline(
        "Full · Developability Screening [Liability+DeepSP+NetSolP+ESM → binary DNN]",
        nodes=[
            n(f"dataset_{ds}", "dataset",          {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 400),
            n(f"lia_{lia}",    "liability_scanner", {},                               450, 160),
            n(f"dsp_{dsp}",    "deepsp",            {},                               450, 360),
            n(f"nsp_{nsp}",    "netsolp",           {},                               450, 560),
            n(f"esm_{esm}",    "esm_embedding",     {"model_size":"8M","pool_mode":"mean"}, 450, 760),
            n(f"cmp_{cmp}",    "compute",           {
                "code": (
                    "# Merge flags: pass=1 if no liabilities AND sap<0.5 AND solubility>0.5\n"
                    "import json, math\n"
                    f"n_lia  = {'{lia_'+lia+'_n_liabilities}'} or 0\n"
                    f"sap    = {'{dsp_'+dsp+'_sap_score}'}     or 0.0\n"
                    f"sol    = {'{nsp_'+nsp+'_heavy_solubility}'} or 0.5\n"
                    "result = {'label': int(n_lia == 0 and sap < 0.5 and sol > 0.5)}\n"
                    "output = result"
                ),
                "output_type": "json",
            }, 750, 400),
            n(f"dnn_{dnn}", "custom_dnn", {
                "architecture_spec": ARCH_DEV_BINARY,
                "epochs": 50, "learning_rate": 0.001,
                "task": "binary_classification", "loss_fn": "bce",
            }, 1050, 500),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",  f"lia_{lia}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",  f"lia_{lia}.light_chain"),
            e(f"dataset_{ds}.heavy_chain",  f"dsp_{dsp}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",  f"dsp_{dsp}.light_chain"),
            e(f"dataset_{ds}.heavy_chain",  f"nsp_{nsp}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",  f"nsp_{nsp}.light_chain"),
            e(f"dataset_{ds}.heavy_chain",  f"esm_{esm}.sequence"),
            e(f"esm_{esm}.embedding",       f"dnn_{dnn}.embedding_input"),
            e(f"dataset_{ds}.labels",       f"dnn_{dnn}.labels"),
        ],
    )


# ── 3. Humanization + Affinity Retention ───────────────────────────────────
# dataset → BioPhi → ESM-8M of humanized seq → DNN (predict ΔKd)
def p3_humanization():
    ds, bph, esm, dnn = uid(), uid(), uid(), uid()
    return pipeline(
        "Full · Humanization Affinity Retention [BioPhi → ESM → DNN regression]",
        nodes=[
            n(f"dataset_{ds}", "dataset",       {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 300),
            n(f"bph_{bph}",    "biophi",         {"humanize_cdrs":False,"iterations":1,"scheme":"imgt"}, 450, 300),
            n(f"esm_{esm}",    "esm_embedding",  {"model_size":"8M","pool_mode":"mean"}, 750, 300),
            n(f"dnn_{dnn}",    "custom_dnn",     {"architecture_spec":ARCH_HUMANIZATION,"epochs":60,"learning_rate":0.001,"task":"regression","loss_fn":"huber"}, 1050, 300),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",          f"bph_{bph}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",          f"bph_{bph}.light_chain"),
            e(f"bph_{bph}.heavy_chain_humanized",   f"esm_{esm}.sequence"),
            e(f"esm_{esm}.embedding",               f"dnn_{dnn}.embedding_input"),
            e(f"dataset_{ds}.labels",               f"dnn_{dnn}.labels"),
        ],
    )


# ── 4. IgLM Variant Generation + Scoring ───────────────────────────────────
# sequence_input → IgLM (CDR redesign) → AbMAP → DNN (rank variants)
def p4_iglm_screening():
    seq, igm, abm, dnn = uid(), uid(), uid(), uid()
    return pipeline(
        "Full · IgLM CDR Redesign + DNN Scoring [generation → AbMAP → DNN]",
        nodes=[
            n(f"seq_{seq}",  "sequence_input",  {"heavy_chain":"","light_chain":""}, 100, 300),
            n(f"igm_{igm}",  "iglm",            {"mode":"redesign","redesign_chain":"H","scheme":"imgt","num_sequences":10,"temperature":1.0,"top_p":0.9}, 400, 300),
            n(f"abm_{abm}",  "abmap",           {"chain_type":"H","task":"embed","embedding_type":"fixed"}, 700, 300),
            n(f"dnn_{dnn}",  "custom_dnn",      {"architecture_spec":ARCH_VARIANT_SCORE,"epochs":50,"learning_rate":0.001,"task":"regression","loss_fn":"auto"}, 1000, 300),
        ],
        edges=[
            e(f"seq_{seq}.heavy_chain",  f"igm_{igm}.heavy_chain"),
            e(f"seq_{seq}.light_chain",  f"igm_{igm}.light_chain"),
            e(f"igm_{igm}.heavy_chain",  f"abm_{abm}.sequence"),
            e(f"abm_{abm}.embedding",    f"dnn_{dnn}.embedding_input"),
        ],
    )


# ── 5. ProGen2 + CHEAP + AbLang Multi-Modal ────────────────────────────────
# sequence_input → ProGen2 → CHEAP + AbLang → DNN (64d+512d → 576d)
def p5_progen2_multimodal():
    seq, prg, chp, abl, dnn = uid(), uid(), uid(), uid(), uid()
    return pipeline(
        "Full · ProGen2 Generation + Multi-Modal DNN [CHEAP+AbLang branches]",
        nodes=[
            n(f"seq_{seq}",  "sequence_input",   {"heavy_chain":"","light_chain":""}, 100, 300),
            n(f"prg_{prg}",  "progen2",           {"mode":"continue","num_sequences":8,"max_length":150,"temperature":1.0,"top_p":0.9}, 400, 300),
            n(f"chp_{chp}",  "cheap_embedding",   {"shorten_factor":1,"dim":64}, 700, 180),
            n(f"abl_{abl}",  "ablang",            {"chain_type":"H","mode":"seqemb"}, 700, 420),
            n(f"dnn_{dnn}",  "custom_dnn",        {"architecture_spec":ARCH_PROGEN_MULTIMODAL,"epochs":60,"learning_rate":0.001,"task":"regression","loss_fn":"auto"}, 1000, 300),
        ],
        edges=[
            e(f"seq_{seq}.heavy_chain",  f"prg_{prg}.sequence"),
            e(f"prg_{prg}.heavy_chain",  f"chp_{chp}.sequence"),
            e(f"prg_{prg}.heavy_chain",  f"abl_{abl}.sequence"),
            e(f"chp_{chp}.embedding",    f"dnn_{dnn}.embedding_input"),
            e(f"abl_{abl}.embedding",    f"dnn_{dnn}.embedding_input_2"),
        ],
    )


# ── 6. CDR Saturation Mutagenesis + DNN Filter ─────────────────────────────
# dataset → CDR Mutator → AbMAP → DNN (select best variants)
def p6_cdr_saturation():
    ds, cdr, abm, dnn = uid(), uid(), uid(), uid()
    return pipeline(
        "Full · CDR Saturation Mutagenesis + DNN Filter [CDR Mutator → AbMAP → DNN]",
        nodes=[
            n(f"dataset_{ds}", "dataset",       {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 300),
            n(f"cdr_{cdr}",    "cdr_mutator",   {"strategy":"random","cdr_h3":True,"cdr_h1":True,"cdr_h2":True,"num_mutations":3,"num_variants":10,"scheme":"imgt"}, 400, 300),
            n(f"abm_{abm}",    "abmap",         {"chain_type":"H","task":"embed","embedding_type":"fixed"}, 700, 300),
            n(f"dnn_{dnn}",    "custom_dnn",    {"architecture_spec":ARCH_CDR_FILTER,"epochs":50,"learning_rate":0.001,"task":"regression","loss_fn":"auto"}, 1000, 300),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",  f"cdr_{cdr}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",  f"cdr_{cdr}.light_chain"),
            e(f"cdr_{cdr}.heavy_chain",     f"abm_{abm}.sequence"),
            e(f"abm_{abm}.embedding",       f"dnn_{dnn}.embedding_input"),
        ],
    )


# ── 7. Structure → Docking → Embedding → DNN ──────────────────────────────
# dataset + target → ImmuneBuilder → HADDOCK3 → AbMAP (seq) → DNN
def p7_docking_pipeline():
    ds, tgt, imb, had, abm, dnn = uid(), uid(), uid(), uid(), uid(), uid()
    return pipeline(
        "Full · Structure+Docking → AbMAP → DNN [ImmuneBuilder → HADDOCK3 → scoring]",
        nodes=[
            n(f"dataset_{ds}", "dataset",       {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 400),
            n(f"target_{tgt}", "target_input",  {"pdb":""}, 100, 700),
            n(f"imb_{imb}",    "immunebuilder", {"num_models":1}, 430, 300),
            n(f"had_{had}",    "haddock3",      {"numbering_scheme":"imgt","rigid_sampling":200,"select_top":1}, 750, 500),
            n(f"abm_{abm}",    "abmap",         {"chain_type":"H","task":"embed","embedding_type":"fixed"}, 430, 700),
            n(f"dnn_{dnn}",    "custom_dnn",    {"architecture_spec":ARCH_DOCKING,"epochs":50,"learning_rate":0.001,"task":"regression","loss_fn":"huber"}, 1050, 500),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",   f"imb_{imb}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",   f"imb_{imb}.light_chain"),
            e(f"imb_{imb}.structure_1",      f"had_{had}.antibody"),
            e(f"target_{tgt}.out",           f"had_{had}.antigen"),
            e(f"dataset_{ds}.heavy_chain",   f"abm_{abm}.sequence"),
            e(f"abm_{abm}.embedding",        f"dnn_{dnn}.embedding_input"),
            e(f"dataset_{ds}.labels",        f"dnn_{dnn}.labels"),
        ],
    )


# ── 8. Solubility / Stability Regression ───────────────────────────────────
# dataset → NetSolP (quick check) + ESM-150M (640d) → DNN regression
def p8_solubility():
    ds, nsp, esm, dnn = uid(), uid(), uid(), uid()
    return pipeline(
        "Full · Solubility Prediction [NetSolP + ESM-150M → DNN regression]",
        nodes=[
            n(f"dataset_{ds}", "dataset",       {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 300),
            n(f"nsp_{nsp}",    "netsolp",        {}, 430, 180),
            n(f"esm_{esm}",    "esm_embedding",  {"model_size":"150M","pool_mode":"mean"}, 430, 420),
            n(f"dnn_{dnn}",    "custom_dnn",     {"architecture_spec":ARCH_SOLUBILITY,"epochs":60,"learning_rate":0.001,"task":"regression","loss_fn":"mse"}, 780, 300),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",  f"nsp_{nsp}.heavy_chain"),
            e(f"dataset_{ds}.light_chain",  f"nsp_{nsp}.light_chain"),
            e(f"dataset_{ds}.heavy_chain",  f"esm_{esm}.sequence"),
            e(f"esm_{esm}.embedding",       f"dnn_{dnn}.embedding_input"),
            e(f"dataset_{ds}.labels",       f"dnn_{dnn}.labels"),
        ],
    )


# ── 9. RFdiffusion Full De-Novo Discovery ──────────────────────────────────
# target → RFdiffusion → ProteinMPNN → ImmuneBuilder → AbMAP → DNN (score)
def p9_rfdiffusion_discovery():
    tgt, rfd, mpnn, imb, abm, dnn = uid(), uid(), uid(), uid(), uid(), uid()
    return pipeline(
        "Full · De-Novo Discovery [RFdiffusion → MPNN → ImmuneBuilder → AbMAP → DNN]",
        nodes=[
            n(f"target_{tgt}", "target_input",   {"pdb":""}, 100, 300),
            n(f"rfd_{rfd}",    "rfdiffusion",    {"num_designs":4,"num_residues":120,"diffusion_steps":50}, 380, 300),
            n(f"mpnn_{mpnn}",  "proteinmpnn",    {"num_sequences":4,"sampling_temp":0.1}, 660, 300),
            n(f"imb_{imb}",    "immunebuilder",  {"num_models":1}, 940, 300),
            n(f"abm_{abm}",    "abmap",          {"chain_type":"H","task":"embed","embedding_type":"fixed"}, 660, 560),
            n(f"dnn_{dnn}",    "custom_dnn",     {"architecture_spec":ARCH_DISCOVERY,"epochs":50,"learning_rate":0.001,"task":"regression","loss_fn":"auto"}, 1200, 430),
        ],
        edges=[
            e(f"target_{tgt}.out",           f"rfd_{rfd}.target_pdb"),
            e(f"rfd_{rfd}.backbone",         f"mpnn_{mpnn}.structure"),
            e(f"mpnn_{mpnn}.sequence",       f"imb_{imb}.heavy_chain"),
            e(f"mpnn_{mpnn}.sequence",       f"abm_{abm}.sequence"),
            e(f"abm_{abm}.embedding",        f"dnn_{dnn}.embedding_input"),
        ],
    )


# ── 10. AbLang + CHEAP Deep Multi-Modal ────────────────────────────────────
# dataset → AbLang + CHEAP → DNN (512d+64d parallel branches → 320d → score)
def p10_ablang_cheap():
    ds, abl, chp, dnn = uid(), uid(), uid(), uid()
    return pipeline(
        "Full · AbLang+CHEAP Multi-Modal DNN [parallel 512d+64d branches]",
        nodes=[
            n(f"dataset_{ds}", "dataset",         {"dataset_id":"","vh_column":"heavy_chain","vl_column":"light_chain","label_column":""}, 100, 300),
            n(f"abl_{abl}",    "ablang",           {"chain_type":"H","mode":"seqemb"}, 430, 180),
            n(f"chp_{chp}",    "cheap_embedding",  {"shorten_factor":1,"dim":64}, 430, 420),
            n(f"dnn_{dnn}",    "custom_dnn",       {"architecture_spec":ARCH_ABLANG_CHEAP,"epochs":60,"learning_rate":0.001,"task":"regression","loss_fn":"auto"}, 780, 300),
        ],
        edges=[
            e(f"dataset_{ds}.heavy_chain",  f"abl_{abl}.sequence"),
            e(f"dataset_{ds}.heavy_chain",  f"chp_{chp}.sequence"),
            e(f"abl_{abl}.embedding",       f"dnn_{dnn}.embedding_input"),
            e(f"chp_{chp}.embedding",       f"dnn_{dnn}.embedding_input_2"),
            e(f"dataset_{ds}.labels",       f"dnn_{dnn}.labels"),
        ],
    )


PIPELINES = [
    p1_dual_embedding_affinity(),
    p2_developability(),
    p3_humanization(),
    p4_iglm_screening(),
    p5_progen2_multimodal(),
    p6_cdr_saturation(),
    p7_docking_pipeline(),
    p8_solubility(),
    p9_rfdiffusion_discovery(),
    p10_ablang_cheap(),
]


# ═══════════════════════════════════════════════════════════════════════════
# Structural validation
# ═══════════════════════════════════════════════════════════════════════════

def validate_architectures() -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "custom_dnn"))
    import json as _json
    import torch
    from run import DynamicDNN

    # (name, arch_spec, input_tensor, slice_map)
    cases = [
        ("Dual-embedding affinity",     ARCH_DUAL_EMB,       torch.randn(4, 832),        {"up_abmap":(0,512),"up_esm":(512,832)}),
        ("Developability binary",        ARCH_DEV_BINARY,     torch.randn(4, 320),        {}),
        ("Humanization retention",       ARCH_HUMANIZATION,   torch.randn(4, 320),        {}),
        ("Variant scoring",              ARCH_VARIANT_SCORE,  torch.randn(4, 512),        {}),
        ("ProGen2 multi-modal",          ARCH_PROGEN_MULTIMODAL, torch.randn(4, 576),     {"up_cheap":(0,64),"up_abla":(64,576)}),
        ("CDR filter",                   ARCH_CDR_FILTER,     torch.randn(4, 512),        {}),
        ("Docking-informed",             ARCH_DOCKING,        torch.randn(4, 512),        {}),
        ("Solubility regression",        ARCH_SOLUBILITY,     torch.randn(4, 640),        {}),
        ("De-novo discovery scoring",    ARCH_DISCOVERY,      torch.randn(4, 512),        {}),
        ("AbLang+CHEAP multi-modal",     ARCH_ABLANG_CHEAP,   torch.randn(4, 576),        {"up_al":(0,512),"up_ch":(512,576)}),
    ]

    print("\n── Architecture validation ──────────────────────────────────────────")
    all_ok = True
    for name, arch, x, slices in cases:
        # Inject slice info when UpstreamInput nodes are present
        arch_copy = _json.loads(_json.dumps(arch))
        for nd in arch_copy["nodes"]:
            if nd["type"] == "UpstreamInput" and nd["id"] in slices:
                s, en = slices[nd["id"]]
                nd["params"]["slice_start"] = s
                nd["params"]["slice_end"]   = en
        try:
            model = DynamicDNN(arch_copy)
            with torch.no_grad():
                out = model(x)
            n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
            print(f"  ✓  {name:<38}  in={list(x.shape)}  out={list(out.shape)}  {n_params:>10,} params")
        except Exception as exc:
            print(f"  ✗  {name:<38}  ERROR: {exc}")
            all_ok = False

    print("─" * 70)
    if all_ok:
        print("All 10 architectures OK.\n")
    else:
        print("Some architectures FAILED.\n")
        sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════
# DB seeding
# ═══════════════════════════════════════════════════════════════════════════

async def seed_db() -> None:
    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.db.models import PipelineRow
    from app.db.session import AsyncSessionLocal
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(PipelineRow).where(PipelineRow.name.like("Full ·%"))
        )).scalars().all()
        for row in existing:
            await db.delete(row)

        for p in PIPELINES:
            db.add(PipelineRow(id=p["id"], name=p["name"], data=json.dumps(p)))

        await db.commit()

    print(f"Seeded {len(PIPELINES)} full pipelines.")
    for p in PIPELINES:
        print(f"  · {p['name']}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--seed-only",     action="store_true")
    args = parser.parse_args()

    if not args.seed_only:
        validate_architectures()
    if not args.validate_only:
        import asyncio
        asyncio.run(seed_db())
