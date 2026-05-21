#!/usr/bin/env python3
"""
Seed 5 new pipelines into the protein_design.db, submit each as a run,
and poll until completion or 5-minute timeout.
"""

import sqlite3
import json
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

# ── Constants ────────────────────────────────────────────────────────────────

DB_PATH = "/Users/oswaldkid/Biotools/AntibodyDiscovery/backend/protein_design.db"
API_BASE = "http://localhost:8000"

VH = "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS"
VL = "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPSRFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK"

# ── Pipeline Definitions ─────────────────────────────────────────────────────

def make_pos(x, y):
    return {"x": float(x), "y": float(y)}

def make_node(id_, tool, params, x, y):
    return {"id": id_, "tool": tool, "params": params, "position": make_pos(x, y)}

def make_edge(src, tgt):
    return {"source": src, "target": tgt}

# Pipeline 1: Developability Characterisation Panel
pipe_dev_panel = {
    "id": "pipe-dev-panel",
    "name": "Developability Characterisation Panel",
    "schema_version": "1",
    "nodes": [
        make_node("seq_in", "sequence_input", {"heavy_chain": VH, "light_chain": VL}, 50, 300),
        make_node("liability", "liability_scanner", {}, 370, 100),
        make_node("biophi", "biophi", {}, 370, 280),
        make_node("deepsp", "deepsp", {}, 370, 460),
        make_node("netsolp", "netsolp", {}, 370, 640),
    ],
    "edges": [
        make_edge("seq_in.heavy_chain", "liability.heavy_chain"),
        make_edge("seq_in.light_chain", "liability.light_chain"),
        make_edge("seq_in.heavy_chain", "biophi.heavy_chain"),
        make_edge("seq_in.light_chain", "biophi.light_chain"),
        make_edge("seq_in.heavy_chain", "deepsp.heavy_chain"),
        make_edge("seq_in.light_chain", "deepsp.light_chain"),
        make_edge("seq_in.heavy_chain", "netsolp.heavy_chain"),
        make_edge("seq_in.light_chain", "netsolp.light_chain"),
    ],
}

# Pipeline 2: Humanization → Liability & Biophysics Screen
pipe_humanize = {
    "id": "pipe-humanize",
    "name": "Humanization → Liability & Biophysics Screen",
    "schema_version": "1",
    "nodes": [
        make_node("seq_in", "sequence_input", {"heavy_chain": VH, "light_chain": VL}, 50, 300),
        make_node("biophi", "biophi", {"iterations": 1}, 330, 300),
        make_node("liability", "liability_scanner", {}, 610, 160),
        make_node("deepsp", "deepsp", {}, 610, 440),
    ],
    "edges": [
        make_edge("seq_in.heavy_chain", "biophi.heavy_chain"),
        make_edge("seq_in.light_chain", "biophi.light_chain"),
        make_edge("biophi.heavy_chain_humanized", "liability.heavy_chain"),
        make_edge("biophi.light_chain_humanized", "liability.light_chain"),
        make_edge("biophi.heavy_chain_humanized", "deepsp.heavy_chain"),
        make_edge("biophi.light_chain_humanized", "deepsp.light_chain"),
    ],
}

# Pipeline 3: IgLM CDR-H3 Redesign → Liability & Humanness
pipe_iglm_screen = {
    "id": "pipe-iglm-screen",
    "name": "IgLM CDR-H3 Redesign → Liability & Humanness",
    "schema_version": "1",
    "nodes": [
        make_node("seq_in", "sequence_input", {"heavy_chain": VH, "light_chain": VL}, 50, 300),
        make_node("iglm", "iglm", {
            "mode": "infill",
            "infill_region": "cdr_h3",
            "redesign_chain": "vh",
            "num_sequences": 5,
            "temperature": 1.0,
            "species": "human",
        }, 330, 300),
        make_node("liability", "liability_scanner", {}, 610, 160),
        make_node("biophi", "biophi", {}, 610, 440),
    ],
    "edges": [
        make_edge("seq_in.heavy_chain", "iglm.heavy_chain"),
        make_edge("seq_in.light_chain", "iglm.light_chain"),
        make_edge("iglm.heavy_chain", "liability.heavy_chain"),
        make_edge("iglm.light_chain", "liability.light_chain"),
        make_edge("iglm.heavy_chain", "biophi.heavy_chain"),
        make_edge("iglm.light_chain", "biophi.light_chain"),
    ],
}

# Pipeline 4: ESMFold → ProteinMPNN → ESM Embedding
pipe_esmfold_mpnn = {
    "id": "pipe-esmfold-mpnn",
    "name": "ESMFold → ProteinMPNN Inverse Folding → ESM Embedding",
    "schema_version": "1",
    "nodes": [
        make_node("seq_in", "sequence_input", {"heavy_chain": VH, "light_chain": VL}, 50, 200),
        make_node("esmfold", "esmfold", {}, 330, 200),
        make_node("mpnn", "proteinmpnn", {"num_sequences": 8, "sampling_temp": 0.1}, 610, 200),
        make_node("esm_emb", "esm_embedding", {"model_size": "650M", "pool_mode": "mean"}, 890, 200),
    ],
    "edges": [
        make_edge("seq_in.heavy_chain", "esmfold.sequence"),
        make_edge("esmfold.structure", "mpnn.structure"),
        make_edge("mpnn.sequence", "esm_emb.sequence"),
    ],
}

# Pipeline 5: IgLM CDR-H3 Redesign → ImmuneBuilder → Liability
pipe_iglm_immuno = {
    "id": "pipe-iglm-immuno",
    "name": "IgLM CDR-H3 Redesign → ImmuneBuilder → Liability",
    "schema_version": "1",
    "nodes": [
        make_node("seq_in", "sequence_input", {"heavy_chain": VH, "light_chain": VL}, 50, 300),
        make_node("iglm", "iglm", {
            "mode": "infill",
            "infill_region": "cdr_h3",
            "redesign_chain": "vh",
            "num_sequences": 3,
            "temperature": 1.0,
            "species": "human",
        }, 330, 300),
        make_node("immunebuilder", "immunebuilder", {"num_models": 1}, 610, 300),
        make_node("liability", "liability_scanner", {}, 890, 300),
    ],
    "edges": [
        make_edge("seq_in.heavy_chain", "iglm.heavy_chain"),
        make_edge("seq_in.light_chain", "iglm.light_chain"),
        make_edge("iglm.heavy_chain", "immunebuilder.heavy_chain"),
        make_edge("iglm.light_chain", "immunebuilder.light_chain"),
        make_edge("iglm.heavy_chain", "liability.heavy_chain"),
        make_edge("iglm.light_chain", "liability.light_chain"),
    ],
}

ALL_PIPELINES = [
    pipe_dev_panel,
    pipe_humanize,
    pipe_iglm_screen,
    pipe_esmfold_mpnn,
    pipe_iglm_immuno,
]

# ── DB helpers ────────────────────────────────────────────────────────────────

def seed_pipelines_to_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    for pipe in ALL_PIPELINES:
        data = json.dumps(pipe)
        cur.execute(
            "INSERT OR REPLACE INTO pipelines (id, name, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (pipe["id"], pipe["name"], data, now, now)
        )
        print(f"  [DB] Upserted pipeline: {pipe['id']} — {pipe['name']}")
    conn.commit()
    conn.close()

# ── API helpers ───────────────────────────────────────────────────────────────

def http_post(url, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def http_get(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())

def submit_run(pipeline):
    url = f"{API_BASE}/api/runs/"
    return http_post(url, pipeline)

def get_run(run_id):
    url = f"{API_BASE}/api/runs/{run_id}/"
    return http_get(url)

# ── Polling ───────────────────────────────────────────────────────────────────

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
POLL_INTERVAL = 5   # seconds
MAX_WAIT = 300       # seconds (5 minutes)

def poll_run(run_id, pipe_name):
    print(f"\n  [POLL] Waiting for run {run_id} ({pipe_name}) ...")
    start = time.time()
    while True:
        elapsed = time.time() - start
        if elapsed > MAX_WAIT:
            print(f"  [POLL] TIMEOUT after {MAX_WAIT}s for run {run_id}")
            return None
        try:
            run_data = get_run(run_id)
        except Exception as e:
            print(f"  [POLL] Error fetching run {run_id}: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        status = run_data.get("status", "unknown")
        print(f"  [POLL] {pipe_name} → status={status} (elapsed {elapsed:.0f}s)")

        if status in TERMINAL_STATUSES:
            return run_data

        time.sleep(POLL_INTERVAL)

# ── Report ────────────────────────────────────────────────────────────────────

def print_run_report(pipe, run_id, run_data):
    print(f"\n{'='*70}")
    print(f"Pipeline : {pipe['name']}")
    print(f"Run ID   : {run_id}")
    status = run_data.get("status", "unknown") if run_data else "TIMEOUT"
    print(f"Status   : {status}")

    if not run_data:
        return

    nodes = run_data.get("nodes", {})
    if isinstance(nodes, dict):
        node_items = nodes.items()
    else:
        node_items = [(n.get("id", "?"), n) for n in nodes]

    # Build node-id → tool map from pipeline snapshot
    snap = run_data.get("pipeline_snapshot") or {}
    tool_map = {n["id"]: n.get("tool", "?") for n in snap.get("nodes", [])}

    print(f"\nNode results:")
    for node_id, node in node_items:
        tool = tool_map.get(node_id, "?")
        node_status = node.get("status", "?")
        error = node.get("error") or ""
        error_short = error[:200] if error else ""
        marker = "✓" if node_status == "succeeded" else ("✗" if node_status == "failed" else "·")
        print(f"  {marker} {node_id} [{tool}] → {node_status}")
        if error_short:
            print(f"      ERROR: {error_short}")

    # Also check node_logs if present
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("STEP 1: Seeding pipelines into DB")
    print("=" * 70)
    seed_pipelines_to_db()

    print("\n" + "=" * 70)
    print("STEP 2: Submitting runs via API")
    print("=" * 70)

    submitted = []  # list of (pipe, run_id)
    for pipe in ALL_PIPELINES:
        try:
            result = submit_run(pipe)
            run_id = result.get("id")
            print(f"  [API] Submitted {pipe['id']} → run_id={run_id}")
            submitted.append((pipe, run_id))
        except Exception as e:
            print(f"  [API] FAILED to submit {pipe['id']}: {e}")
            submitted.append((pipe, None))

    print("\n" + "=" * 70)
    print("STEP 3: Polling for completion (max 5 min per run)")
    print("=" * 70)

    results = []
    for pipe, run_id in submitted:
        if run_id is None:
            print(f"\n  [SKIP] {pipe['name']} — no run ID (submission failed)")
            results.append((pipe, run_id, None))
            continue
        run_data = poll_run(run_id, pipe["name"])
        results.append((pipe, run_id, run_data))

    print("\n" + "=" * 70)
    print("FINAL REPORT")
    print("=" * 70)

    for pipe, run_id, run_data in results:
        print_run_report(pipe, run_id, run_data)

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for pipe, run_id, run_data in results:
        if run_data is None:
            status = "FAILED/TIMEOUT" if run_id else "NOT SUBMITTED"
        else:
            status = run_data.get("status", "unknown").upper()
        print(f"  {pipe['id']:25s} | run={run_id or 'N/A':36s} | {status}")

    print()

if __name__ == "__main__":
    main()
