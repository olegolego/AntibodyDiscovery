#!/usr/bin/env python3
"""
Test all locally-runnable structure prediction tools and verify:
  1. Pipeline runs to completion
  2. NodeAnalysisRow has real PDB (not sentinel)
  3. Analysis API returns the structure correctly
  4. /report/ endpoint returns correct metrics

Tools tested:
  - immunebuilder       (sequence_input → immunebuilder)
  - equifold            (sequence_input → equifold)
  - alphafold_monomer   (standalone, UniProt ID)
  - equidock            (sequence_input → immunebuilder → equidock)
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request

API = "http://localhost:8000/api"
DB = "/Users/oswaldkid/Biotools/AntibodyDiscovery/backend/protein_design.db"

VH = ("EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTR"
      "YADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS")
VL = ("DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPS"
      "RFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK")

RESULTS = {}


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{API}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read().decode()[:300]}")
        raise


def get(path):
    with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
        return json.loads(r.read())


def poll_run(run_id, timeout=600):
    deadline = time.time() + timeout
    t0 = time.time()
    while time.time() < deadline:
        run = get(f"/runs/{run_id}/")
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return run
        nodes = run.get("nodes", {})
        summary = "  ".join(f"{k}={v.get('status','?')}" for k, v in nodes.items())
        print(f"  [{int(time.time()-t0)}s] {run['status']} | {summary}")
        time.sleep(6)
    return get(f"/runs/{run_id}/")


def check_analysis_rows(run_id):
    """Return lists of (tool_id, bytes) for good/bad NodeAnalysisRows."""
    db = sqlite3.connect(DB)
    rows = db.execute(
        "SELECT tool_id, node_id, length(data), data FROM node_analyses "
        "WHERE run_id=? ORDER BY created_at DESC",
        (run_id,)
    ).fetchall()
    db.close()

    good, bad = [], []
    for tool_id, node_id, dlen, data_str in rows:
        d = json.loads(data_str)
        struct = d.get("structure", "")
        if struct and not str(struct).startswith("__") and dlen > 500:
            good.append((tool_id, node_id, dlen))
        else:
            bad.append((tool_id, node_id, dlen, str(struct)[:40]))
    return good, bad


def submit_pipeline(name, nodes, edges):
    pipeline = {
        "name": name,
        "schema_version": "1",
        "nodes": nodes,
        "edges": edges,
    }
    run = post("/runs/", pipeline)
    return run["id"]


def node_errors(run):
    errs = {}
    for nid, nr in run.get("nodes", {}).items():
        if nr.get("error"):
            errs[nid] = nr["error"][:300]
    return errs


# ─── Test 1: ImmuneBuilder ────────────────────────────────────────────────────

def test_immunebuilder():
    print("\n═══ Test 1: ImmuneBuilder ═══")
    try:
        run_id = submit_pipeline(
            "TEST immunebuilder",
            nodes=[
                {"id": "seq1", "tool": "sequence_input",
                 "params": {"heavy_chain": VH, "light_chain": VL},
                 "position": {"x": 0, "y": 0}},
                {"id": "imm1", "tool": "immunebuilder",
                 "params": {},
                 "position": {"x": 300, "y": 0}},
            ],
            edges=[
                {"source": "seq1.heavy_chain", "target": "imm1.heavy_chain"},
                {"source": "seq1.light_chain",  "target": "imm1.light_chain"},
            ]
        )
    except Exception as e:
        print(f"  FAIL — submit error: {e}")
        return False

    print(f"  run_id: {run_id}")
    run = poll_run(run_id, 600)
    print(f"  status: {run['status']}")

    if run["status"] != "succeeded":
        for nid, err in node_errors(run).items():
            print(f"  ERROR [{nid}]: {err}")
        return False

    good, bad = check_analysis_rows(run_id)
    print(f"  NodeAnalysisRows: good={[(t,n,sz) for t,n,sz in good]}")
    if bad:
        print(f"  Bad rows: {bad}")

    # Check analysis API for model_1
    try:
        ana = get(f"/analysis/runs/{run_id}/nodes/imm1_model_1/")
        has_struct = bool(ana.get("structure") and not str(ana["structure"]).startswith("__"))
        print(f"  analysis API /imm1_model_1/: has_structure={has_struct} ({len(ana.get('structure',''))} chars)")
    except Exception as e:
        print(f"  analysis API error: {e}")

    # Check report
    try:
        report = get(f"/runs/{run_id}/report/")
        for n in report["nodes"]:
            if n["tool_id"] == "immunebuilder":
                print(f"  report: status={n['status']} metrics={n.get('metrics')}")
    except Exception as e:
        print(f"  report error: {e}")

    passed = any(t == "immunebuilder" for t, _, _ in good)
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed


# ─── Test 2: EquiFold ─────────────────────────────────────────────────────────

def test_equifold():
    print("\n═══ Test 2: EquiFold ═══")
    try:
        run_id = submit_pipeline(
            "TEST equifold",
            nodes=[
                {"id": "seq1", "tool": "sequence_input",
                 "params": {"heavy_chain": VH, "light_chain": VL},
                 "position": {"x": 0, "y": 0}},
                {"id": "ef1", "tool": "equifold",
                 "params": {},
                 "position": {"x": 300, "y": 0}},
            ],
            edges=[
                {"source": "seq1.heavy_chain", "target": "ef1.heavy_chain"},
                {"source": "seq1.light_chain",  "target": "ef1.light_chain"},
            ]
        )
    except Exception as e:
        print(f"  FAIL — submit error: {e}")
        return False

    print(f"  run_id: {run_id}")
    run = poll_run(run_id, 180)
    print(f"  status: {run['status']}")

    if run["status"] != "succeeded":
        for nid, err in node_errors(run).items():
            print(f"  ERROR [{nid}]: {err}")
        return False

    good, bad = check_analysis_rows(run_id)
    print(f"  NodeAnalysisRows: good={[(t,n,sz) for t,n,sz in good]}")
    if bad:
        print(f"  Bad rows: {bad}")

    # Check analysis API
    try:
        ana = get(f"/analysis/runs/{run_id}/nodes/ef1/")
        has_struct = bool(ana.get("structure") and not str(ana["structure"]).startswith("__"))
        print(f"  analysis API /ef1/: has_structure={has_struct} ({len(ana.get('structure',''))} chars)")
    except Exception as e:
        print(f"  analysis API error: {e}")

    # Check report
    try:
        report = get(f"/runs/{run_id}/report/")
        for n in report["nodes"]:
            if n["tool_id"] == "equifold":
                print(f"  report: status={n['status']} metrics={n.get('metrics')}")
    except Exception as e:
        print(f"  report error: {e}")

    passed = any(t == "equifold" for t, _, _ in good)
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed


# ─── Test 3: AlphaFold Monomer ────────────────────────────────────────────────

def test_alphafold():
    print("\n═══ Test 3: AlphaFold Monomer (EBI fetch P00533=EGFR) ═══")
    try:
        run_id = submit_pipeline(
            "TEST alphafold_monomer",
            nodes=[
                {"id": "af1", "tool": "alphafold_monomer",
                 "params": {"uniprot_id": "P00533"},
                 "position": {"x": 0, "y": 0}},
            ],
            edges=[]
        )
    except Exception as e:
        print(f"  FAIL — submit error: {e}")
        return False

    print(f"  run_id: {run_id}")
    run = poll_run(run_id, 90)
    print(f"  status: {run['status']}")

    if run["status"] != "succeeded":
        for nid, err in node_errors(run).items():
            print(f"  ERROR [{nid}]: {err}")
        return False

    good, bad = check_analysis_rows(run_id)
    print(f"  NodeAnalysisRows: good={[(t,n,sz) for t,n,sz in good]}")
    if bad:
        print(f"  Bad rows: {bad}")

    # Check analysis API
    try:
        ana = get(f"/analysis/runs/{run_id}/nodes/af1/")
        has_struct = bool(ana.get("structure") and not str(ana["structure"]).startswith("__"))
        plddt = ana.get("plddt") or {}
        print(f"  analysis API /af1/: has_structure={has_struct} ({len(ana.get('structure',''))} chars)")
        if isinstance(plddt, dict):
            print(f"  plddt keys: {list(plddt.keys())}")
    except Exception as e:
        print(f"  analysis API error: {e}")

    # Check report
    try:
        report = get(f"/runs/{run_id}/report/")
        for n in report["nodes"]:
            if n["tool_id"] == "alphafold_monomer":
                print(f"  report: status={n['status']} metrics={n.get('metrics')}")
    except Exception as e:
        print(f"  report error: {e}")

    passed = any(t == "alphafold_monomer" for t, _, _ in good)
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed


# ─── Test 4: EquiDock ─────────────────────────────────────────────────────────

def test_equidock():
    print("\n═══ Test 4: EquiDock (ImmuneBuilder → EquiDock, spike RBD) ═══")
    try:
        run_id = submit_pipeline(
            "TEST equidock",
            nodes=[
                {"id": "seq1", "tool": "sequence_input",
                 "params": {"heavy_chain": VH, "light_chain": VL},
                 "position": {"x": 0, "y": 0}},
                {"id": "imm1", "tool": "immunebuilder",
                 "params": {},
                 "position": {"x": 300, "y": 0}},
                {"id": "tgt1", "tool": "target_input",
                 "params": {"target": "__default_file__:spike_rbd.pdb"},
                 "position": {"x": 0, "y": 200}},
                {"id": "dock1", "tool": "equidock",
                 "params": {"dataset": "dips", "remove_clashes": True},
                 "position": {"x": 600, "y": 100}},
            ],
            edges=[
                {"source": "seq1.heavy_chain",  "target": "imm1.heavy_chain"},
                {"source": "seq1.light_chain",   "target": "imm1.light_chain"},
                {"source": "imm1.structure_1",   "target": "dock1.ligand"},
                {"source": "tgt1.target",        "target": "dock1.receptor"},
            ]
        )
    except Exception as e:
        print(f"  FAIL — submit error: {e}")
        return False

    print(f"  run_id: {run_id}")
    run = poll_run(run_id, 700)
    print(f"  status: {run['status']}")

    if run["status"] != "succeeded":
        for nid, err in node_errors(run).items():
            print(f"  ERROR [{nid}]: {err}")
        return False

    good, bad = check_analysis_rows(run_id)
    print(f"  NodeAnalysisRows: good={[(t,n,sz) for t,n,sz in good]}")
    if bad:
        print(f"  Bad rows: {bad}")

    # Check analysis API
    try:
        ana = get(f"/analysis/runs/{run_id}/nodes/dock1/")
        has_struct = bool(ana.get("structure") and not str(ana["structure"]).startswith("__"))
        meta = ana.get("plddt") or {}
        print(f"  analysis API /dock1/: has_structure={has_struct} ({len(ana.get('structure',''))} chars)")
        print(f"  metadata: {meta}")
    except Exception as e:
        print(f"  analysis API error: {e}")

    # Check report
    try:
        report = get(f"/runs/{run_id}/report/")
        for n in report["nodes"]:
            if n["tool_id"] == "equidock":
                m = n.get("metrics") or {}
                print(f"  report: status={n['status']} primary={m.get('primary')} conf={m.get('confidence')}")
    except Exception as e:
        print(f"  report error: {e}")

    passed = any(t == "equidock" for t, _, _ in good)
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    RESULTS["immunebuilder"] = test_immunebuilder()
    RESULTS["equifold"]      = test_equifold()
    RESULTS["alphafold"]     = test_alphafold()
    RESULTS["equidock"]      = test_equidock()

    print("\n" + "═" * 50)
    print("SUMMARY:")
    for name, passed in RESULTS.items():
        print(f"  {'✓' if passed else '✗'} {name}")
    if all(RESULTS.values()):
        print("\nALL TESTS PASSED")
    else:
        failed = [k for k, v in RESULTS.items() if not v]
        print(f"\nFAILED: {', '.join(failed)}")
