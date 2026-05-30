#!/usr/bin/env python3
"""
Seed and run a minimal EquiDock test pipeline:
  SequenceInput → ImmuneBuilder (1 model) → EquiDock (DIPS, spike-RBD receptor)

On success, prints the docking metadata, ligand residue count, and
confirms NodeAnalysisRow + DockingResultRow were written to the DB.
"""

import json
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

DB_PATH = "/Users/oswaldkid/Biotools/AntibodyDiscovery/backend/protein_design.db"
API_BASE = "http://localhost:8000"

# Trastuzumab VH/VL — a well-characterised antibody, good test case
VH = (
    "EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTR"
    "YADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS"
)
VL = (
    "DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPS"
    "RFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK"
)

PIPELINE = {
    "id":             "pipe-equidock-test",
    "name":           "EquiDock Test — ImmuneBuilder → EquiDock (spike RBD)",
    "schema_version": "1",
    "nodes": [
        {
            "id":       "seq_in",
            "tool":     "sequence_input",
            "params":   {"heavy_chain": VH, "light_chain": VL},
            "position": {"x": 50,  "y": 300},
        },
        {
            "id":       "immuno",
            "tool":     "immunebuilder",
            "params":   {"num_models": 1},
            "position": {"x": 350, "y": 300},
        },
        {
            "id":       "target",
            "tool":     "target_input",
            "params":   {"target": "__default_file__:spike_rbd.pdb"},
            "position": {"x": 350, "y": 520},
        },
        {
            "id":       "dock",
            "tool":     "equidock",
            "params":   {"dataset": "dips", "remove_clashes": True},
            "position": {"x": 650, "y": 400},
        },
    ],
    "edges": [
        {"source": "seq_in.heavy_chain",  "target": "immuno.heavy_chain"},
        {"source": "seq_in.light_chain",  "target": "immuno.light_chain"},
        {"source": "immuno.structure_1",  "target": "dock.ligand"},
        {"source": "target.target",       "target": "dock.receptor"},
    ],
}


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def http_post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as r:
        return json.loads(r.read())


# ── DB helpers ────────────────────────────────────────────────────────────────

def seed_pipeline() -> None:
    conn = sqlite3.connect(DB_PATH)
    now  = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO pipelines (id, name, data, created_at, updated_at) VALUES (?,?,?,?,?)",
        (PIPELINE["id"], PIPELINE["name"], json.dumps(PIPELINE), now, now),
    )
    conn.commit()
    conn.close()
    print(f"[DB] Upserted pipeline: {PIPELINE['id']}")


def check_db(run_id: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    cur.execute("SELECT tool_id, node_id, LENGTH(data) FROM node_analyses WHERE run_id=?", (run_id,))
    analyses = cur.fetchall()

    cur.execute("SELECT tool_id, node_id, antigen_label, LENGTH(best_complex_pdb), extra_data "
                "FROM docking_results WHERE run_id=?", (run_id,))
    docking = cur.fetchall()

    conn.close()

    print("\n── DB check ─────────────────────────────────────────────")
    print(f"  node_analyses rows : {len(analyses)}")
    for tool, node, sz in analyses:
        print(f"    [{tool}] node={node}  data={sz} bytes")

    print(f"  docking_results rows: {len(docking)}")
    for tool, node, antigen, pdb_len, extra in docking:
        meta = json.loads(extra) if extra else {}
        print(f"    [{tool}] node={node}  antigen={antigen}  pdb={pdb_len} bytes")
        print(f"      metadata: {meta}")


# ── Poll ──────────────────────────────────────────────────────────────────────

TERMINAL = {"succeeded", "failed", "cancelled"}
POLL_INTERVAL = 8
TIMEOUT = 900  # 15 min — ImmuneBuilder can be slow on CPU


def poll(run_id: str):
    print(f"\n[POLL] run_id={run_id}")
    t0 = time.time()
    while True:
        elapsed = time.time() - t0
        if elapsed > TIMEOUT:
            print(f"[POLL] TIMEOUT after {TIMEOUT}s")
            return None
        try:
            run = http_get(f"{API_BASE}/api/runs/{run_id}/")
        except Exception as e:
            print(f"[POLL] fetch error: {e}")
            time.sleep(POLL_INTERVAL)
            continue

        status = run.get("status", "?")
        nodes  = run.get("nodes", {})
        node_summary = "  ".join(
            f"{nid}={n.get('status','?')}" for nid, n in nodes.items()
        )
        print(f"  [{elapsed:5.0f}s] run={status}  nodes: {node_summary}")

        if status in TERMINAL:
            return run
        time.sleep(POLL_INTERVAL)


# ── Report ────────────────────────────────────────────────────────────────────

def print_report(run: dict) -> None:
    status = run.get("status")
    nodes  = run.get("nodes", {})
    snap   = run.get("pipeline_snapshot") or {}
    tool_map = {n["id"]: n.get("tool", "?") for n in snap.get("nodes", [])}

    print(f"\n{'='*68}")
    print(f"Pipeline : {PIPELINE['name']}")
    print(f"Run ID   : {run.get('id')}")
    print(f"Status   : {status}")
    print()

    for nid, n in nodes.items():
        tool    = tool_map.get(nid, "?")
        ns      = n.get("status", "?")
        marker  = "✓" if ns == "succeeded" else ("✗" if ns == "failed" else "·")
        err     = (n.get("error") or "")[:200]
        outputs = n.get("outputs") or {}
        print(f"  {marker} {nid} [{tool}] → {ns}")
        if err:
            print(f"      ERROR: {err}")
        if nid == "dock" and ns == "succeeded":
            meta = outputs.get("metadata") or {}
            pdb  = outputs.get("best_complex") or ""
            print(f"      metadata     : {meta}")
            print(f"      complex PDB  : {len(pdb)} chars")

    print(f"{'='*68}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 68)
    print("Step 1 — seed pipeline into DB")
    seed_pipeline()

    print("\nStep 2 — submit run via API")
    try:
        run_resp = http_post(f"{API_BASE}/api/runs/", PIPELINE)
    except urllib.error.URLError as e:
        print(f"ERROR: Cannot reach backend at {API_BASE} — is it running? ({e})")
        raise SystemExit(1)

    run_id = run_resp.get("id")
    print(f"  run_id = {run_id}")

    print("\nStep 3 — polling until terminal state")
    run = poll(run_id)
    if run is None:
        raise SystemExit("Run timed out")

    print_report(run)

    print("\nStep 4 — DB verification")
    check_db(run_id)

    if run.get("status") != "succeeded":
        raise SystemExit(f"Run did not succeed: {run.get('status')}")

    print("\n✓ EquiDock test PASSED")


if __name__ == "__main__":
    main()
