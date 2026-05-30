#!/usr/bin/env python3
"""
Comprehensive tool test suite.
Tests every locally-runnable, non-wip tool in the AntibodyDiscovery platform.

Skipped (require external server or are too slow for CI):
  - esmfold / abmap / cheap_embedding / proteinmpnn  (http, no server configured)
  - haddock3       (7200s timeout)
  - rfdiffusion    (30+ min)
  - gromacs_mmpbsa (requires docked complex + MD infrastructure)
  - dnn_mlde       (requires full ML dataset pipeline)
  - rcc_mlde       (requires full ML dataset pipeline)
  - loop / loop_start / loop_end / loop_objective  (control flow, tested via loop pipelines)
  - diffusion_design  (wip=true)
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request

API   = "http://localhost:8000/api"
DB    = "/Users/oswaldkid/Biotools/AntibodyDiscovery/backend/protein_design.db"
VH    = ("EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTR"
         "YADSVKGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS")
VL    = ("DIQMTQSPSSLSASVGDRVTITCRASQDVNTAVAWYQQKPGKAPKLLIYSASFLYSGVPS"
         "RFSGSRSGTDFTLTISSLQPEDFATYYCQQHYTTPPTFGQGTKVEIK")

RESULTS = {}
_pdb_cache = {}   # cache immunebuilder run_id so structure tests share it


# ─── HTTP helpers ─────────────────────────────────────────────────────────────

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{API}{path}", data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:400]
        raise RuntimeError(f"HTTP {e.code}: {body}")


def get(path):
    with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
        return json.loads(r.read())


def poll(run_id, timeout=600):
    t0 = time.time()
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = get(f"/runs/{run_id}/")
        if run["status"] in ("succeeded", "failed", "cancelled"):
            return run
        nodes = run.get("nodes", {})
        summary = "  ".join(f"{k}={v.get('status','?')}" for k, v in nodes.items())
        print(f"    [{int(time.time()-t0)}s] {run['status']} | {summary}")
        time.sleep(6)
    return get(f"/runs/{run_id}/")


def submit(name, nodes, edges=None):
    return post("/runs/", {
        "name": name,
        "schema_version": "1",
        "nodes": nodes,
        "edges": edges or [],
    })["id"]


def node_errors(run):
    return {k: v["error"][:300] for k, v in run.get("nodes", {}).items() if v.get("error")}


def check_run(run, test_name):
    if run["status"] != "succeeded":
        errs = node_errors(run)
        print(f"  FAIL — status={run['status']}")
        for nid, err in errs.items():
            print(f"    [{nid}]: {err}")
        return False
    return True


def run_test(name, nodes, edges=None, timeout=180):
    """Submit, poll, return (passed, run) tuple."""
    try:
        run_id = submit(name, nodes, edges)
    except Exception as e:
        print(f"  FAIL — submit error: {e}")
        return False, {}
    print(f"  run_id: {run_id}")
    run = poll(run_id, timeout)
    print(f"  status: {run['status']}")
    return check_run(run, name), run


# ─── Shared node builders ─────────────────────────────────────────────────────

def seq_node(x=0, y=0):
    return {"id": "seq1", "tool": "sequence_input",
            "params": {"heavy_chain": VH, "light_chain": VL},
            "position": {"x": x, "y": y}}

def imm_node(x=300, y=0):
    return {"id": "imm1", "tool": "immunebuilder",
            "params": {}, "position": {"x": x, "y": y}}

def tgt_node(x=0, y=200):
    return {"id": "tgt1", "tool": "target_input",
            "params": {"target": "__default_file__:spike_rbd.pdb"},
            "position": {"x": x, "y": y}}

def seq_to_imm():
    return [
        {"source": "seq1.heavy_chain", "target": "imm1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "imm1.light_chain"},
    ]


def _get_imm_structure():
    """Return a real PDB from a recent immunebuilder run (cached)."""
    if "pdb" in _pdb_cache:
        return _pdb_cache["pdb"]
    db = sqlite3.connect(DB)
    row = db.execute(
        "SELECT data FROM node_analyses "
        "WHERE tool_id='immunebuilder' AND length(data)>50000 "
        "ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    db.close()
    if row:
        d = json.loads(row[0])
        pdb = d.get("structure", "")
        if pdb:
            _pdb_cache["pdb"] = pdb
            return pdb
    raise RuntimeError("No immunebuilder PDB found in DB — run immunebuilder test first")


# ─── Test functions ────────────────────────────────────────────────────────────

def test_echo():
    print("\n═══ echo ═══")
    passed, run = run_test("TEST echo", [
        {"id": "e1", "tool": "echo",
         "params": {"data": {"hello": "world", "n": 42}},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run.get("nodes", {}).get("e1", {}).get("outputs", {})
        print(f"  output: {out}")
    RESULTS["echo"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_sequence_input():
    print("\n═══ sequence_input ═══")
    passed, run = run_test("TEST sequence_input", [seq_node()])
    if passed:
        out = run["nodes"].get("seq1", {}).get("outputs", {})
        vh_len = len(out.get("heavy_chain", ""))
        print(f"  VH len={vh_len}, VL len={len(out.get('light_chain',''))}")
    RESULTS["sequence_input"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_target_input():
    print("\n═══ target_input ═══")
    passed, run = run_test("TEST target_input", [tgt_node()])
    if passed:
        out = run["nodes"].get("tgt1", {}).get("outputs", {})
        target = out.get("target", "")
        print(f"  target: {len(target)} chars")
    RESULTS["target_input"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_sequence_db():
    print("\n═══ sequence_db ═══")
    passed, run = run_test("TEST sequence_db", [
        {"id": "db1", "tool": "sequence_db",
         "params": {"heavy_chain": VH},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("db1", {}).get("outputs", {})
        print(f"  heavy_chain: {len(out.get('heavy_chain',''))} chars")
    RESULTS["sequence_db"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_compute():
    print("\n═══ compute ═══")
    passed, run = run_test("TEST compute", [
        {"id": "c1", "tool": "compute",
         "params": {"code": "result = {'sum': 1+2, 'hello': 'world'}"},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("c1", {}).get("outputs", {})
        print(f"  result: {out.get('result')}")
    RESULTS["compute"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_ablang():
    print("\n═══ ablang ═══")
    passed, run = run_test("TEST ablang", [
        seq_node(),
        {"id": "abl1", "tool": "ablang",
         "params": {"mode": "seqcoding"},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "abl1.vh"},
        {"source": "seq1.light_chain",  "target": "abl1.vl"},
    ])
    if passed:
        out = run["nodes"].get("abl1", {}).get("outputs", {})
        print(f"  n={out.get('n')}, metadata={out.get('metadata')}")
    RESULTS["ablang"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_esm_embedding():
    print("\n═══ esm_embedding ═══")
    passed, run = run_test("TEST esm_embedding", [
        seq_node(),
        {"id": "esm1", "tool": "esm_embedding",
         "params": {"model_size": "8M"},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "esm1.vh"},
        {"source": "seq1.light_chain",  "target": "esm1.vl"},
    ])
    if passed:
        out = run["nodes"].get("esm1", {}).get("outputs", {})
        print(f"  n={out.get('n')}, metadata={out.get('metadata')}")
    RESULTS["esm_embedding"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_biophi():
    print("\n═══ biophi ═══")
    passed, run = run_test("TEST biophi", [
        seq_node(),
        {"id": "bp1", "tool": "biophi",
         "params": {},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "bp1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "bp1.light_chain"},
    ])
    if passed:
        out = run["nodes"].get("bp1", {}).get("outputs", {})
        print(f"  heavy_mutations={out.get('heavy_mutations')}, light_mutations={out.get('light_mutations')}")
    RESULTS["biophi"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_deepsp():
    print("\n═══ deepsp ═══")
    passed, run = run_test("TEST deepsp", [
        seq_node(),
        {"id": "dsp1", "tool": "deepsp",
         "params": {},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "dsp1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "dsp1.light_chain"},
    ])
    if passed:
        out = run["nodes"].get("dsp1", {}).get("outputs", {})
        print(f"  sap_score={out.get('sap_score')}")
    RESULTS["deepsp"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_netsolp():
    print("\n═══ netsolp ═══")
    passed, run = run_test("TEST netsolp", [
        seq_node(),
        {"id": "ns1", "tool": "netsolp",
         "params": {},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "ns1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "ns1.light_chain"},
    ])
    if passed:
        out = run["nodes"].get("ns1", {}).get("outputs", {})
        print(f"  heavy_solubility={out.get('heavy_solubility')}")
    RESULTS["netsolp"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_liability_scanner():
    print("\n═══ liability_scanner ═══")
    passed, run = run_test("TEST liability_scanner", [
        seq_node(),
        {"id": "ls1", "tool": "liability_scanner",
         "params": {},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "ls1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "ls1.light_chain"},
    ])
    if passed:
        out = run["nodes"].get("ls1", {}).get("outputs", {})
        print(f"  n_liabilities={out.get('n_liabilities')}, summary keys={list((out.get('summary') or {}).keys())[:4]}")
    RESULTS["liability_scanner"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_cdr_mutator():
    print("\n═══ cdr_mutator ═══")
    passed, run = run_test("TEST cdr_mutator", [
        seq_node(),
        {"id": "cdr1", "tool": "cdr_mutator",
         "params": {"strategy": "random", "num_variants": 3},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "cdr1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "cdr1.light_chain"},
    ])
    if passed:
        out = run["nodes"].get("cdr1", {}).get("outputs", {})
        seqs = out.get("sequences") or {}
        n = seqs.get("n") if isinstance(seqs, dict) else 0
        print(f"  variants: n={n}")
    RESULTS["cdr_mutator"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")
    return passed, run


def test_developability_filter():
    print("\n═══ developability_filter ═══")
    # Pass the batch sequences directly as params
    batch = {"n": 2, "variants": [
        {"vh": VH, "vl": VL},
        {"vh": VH[:100], "vl": VL[:90]},
    ]}
    passed, run = run_test("TEST developability_filter", [
        {"id": "df1", "tool": "developability_filter",
         "params": {"sequences": batch},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("df1", {}).get("outputs", {})
        seqs = out.get("sequences") or {}
        n = seqs.get("n") if isinstance(seqs, dict) else out.get("n_feasible")
        print(f"  n_feasible={out.get('n_feasible')}, returned_n={n}")
    RESULTS["developability_filter"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_rank():
    print("\n═══ rank ═══")
    scores = {"varA": 0.9, "varB": 0.3, "varC": 0.7}
    passed, run = run_test("TEST rank", [
        {"id": "r1", "tool": "rank",
         "params": {"score_var": "scores", "scores": scores, "order": "descending"},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("r1", {}).get("outputs", {})
        ranking = out.get("ranking") or []
        print(f"  ranking: {[(r['rank'],r['name'],r['score']) for r in ranking[:3]]}")
    RESULTS["rank"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_filter():
    print("\n═══ filter ═══")
    scores = {"varA": 0.9, "varB": 0.3, "varC": 0.7}
    passed, run = run_test("TEST filter", [
        {"id": "f1", "tool": "filter",
         "params": {"score_var": "scores", "scores": scores, "min_score": 0.5},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("f1", {}).get("outputs", {})
        print(f"  count={out.get('count')}, removed_count={out.get('removed_count')}")
    RESULTS["filter"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_evaluate():
    print("\n═══ evaluate ═══")
    scores = {"varA": 0.9, "varB": 0.3, "varC": 0.7}
    passed, run = run_test("TEST evaluate", [
        {"id": "ev1", "tool": "evaluate",
         "params": {"score_var": "scores", "scores": scores},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("ev1", {}).get("outputs", {})
        print(f"  summary={out.get('summary')}")
    RESULTS["evaluate"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_choose():
    print("\n═══ choose ═══")
    scores = {"varA": 0.9, "varB": 0.3, "varC": 0.7}
    passed, run = run_test("TEST choose", [
        {"id": "ch1", "tool": "choose",
         "params": {"score_var": "scores", "scores": scores, "strategy": "top_score", "n": 1},
         "position": {"x": 0, "y": 0}},
    ])
    if passed:
        out = run["nodes"].get("ch1", {}).get("outputs", {})
        print(f"  chosen: name={out.get('name')}, score={out.get('score')}")
    RESULTS["choose"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_progen2():
    print("\n═══ progen2 ═══")
    passed, run = run_test("TEST progen2", [
        {"id": "pg1", "tool": "progen2",
         "params": {"mode": "antibody", "num_sequences": 2},
         "position": {"x": 0, "y": 0}},
    ], timeout=300)
    if passed:
        out = run["nodes"].get("pg1", {}).get("outputs", {})
        print(f"  variant_1 type={type(out.get('variant_1')).__name__}, metadata={out.get('metadata')}")
    RESULTS["progen2"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_iglm():
    print("\n═══ iglm ═══")
    passed, run = run_test("TEST iglm", [
        seq_node(),
        {"id": "ig1", "tool": "iglm",
         "params": {"mode": "infill", "infill_region": "cdrh3", "num_variants": 2},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "ig1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "ig1.light_chain"},
    ], timeout=300)
    if passed:
        out = run["nodes"].get("ig1", {}).get("outputs", {})
        print(f"  variant_1 len={len(out.get('variant_1') or '')}, metadata={out.get('metadata')}")
    RESULTS["iglm"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_pdbfixer():
    print("\n═══ pdbfixer ═══")
    try:
        pdb = _get_imm_structure()
    except Exception as e:
        print(f"  SKIP — {e}")
        RESULTS["pdbfixer"] = None
        return
    passed, run = run_test("TEST pdbfixer", [
        {"id": "fx1", "tool": "pdbfixer",
         "params": {"structure": pdb},
         "position": {"x": 0, "y": 0}},
    ], timeout=120)
    if passed:
        out = run["nodes"].get("fx1", {}).get("outputs", {})
        struct = out.get("fixed_structure", "")
        print(f"  fixed_structure: {len(struct)} chars, report={out.get('report')}")
    RESULTS["pdbfixer"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_superwater():
    print("\n═══ superwater ═══")
    try:
        pdb = _get_imm_structure()
    except Exception as e:
        print(f"  SKIP — {e}")
        RESULTS["superwater"] = None
        return
    passed, run = run_test("TEST superwater", [
        {"id": "sw1", "tool": "superwater",
         "params": {"structure": pdb},
         "position": {"x": 0, "y": 0}},
    ], timeout=600)
    if passed:
        out = run["nodes"].get("sw1", {}).get("outputs", {})
        struct = out.get("hydrated_structure", "")
        wc = out.get("water_count") or {}
        print(f"  hydrated_structure: {len(struct)} chars, water_count={wc}")
        # Verify NodeAnalysisRow
        db = sqlite3.connect(DB)
        row = db.execute(
            "SELECT tool_id, length(data) FROM node_analyses WHERE run_id=? AND tool_id='superwater'",
            (run["id"],)
        ).fetchone()
        db.close()
        if row:
            print(f"  NodeAnalysisRow: tool={row[0]}, bytes={row[1]}")
    RESULTS["superwater"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_megadock():
    print("\n═══ megadock (slow ~10min) ═══")
    try:
        pdb = _get_imm_structure()
    except Exception as e:
        print(f"  SKIP — {e}")
        RESULTS["megadock"] = None
        return

    # Use immunebuilder output as both ligand and receptor (just for testing)
    passed, run = run_test("TEST megadock", [
        seq_node(),
        imm_node(300, 0),
        tgt_node(0, 200),
        {"id": "md1", "tool": "megadock",
         "params": {},
         "position": {"x": 600, "y": 100}},
    ], edges=[
        {"source": "seq1.heavy_chain", "target": "imm1.heavy_chain"},
        {"source": "seq1.light_chain",  "target": "imm1.light_chain"},
        {"source": "imm1.structure_1",   "target": "md1.ligand"},
        {"source": "tgt1.target",        "target": "md1.receptor"},
    ], timeout=700)
    if passed:
        out = run["nodes"].get("md1", {}).get("outputs", {})
        meta = out.get("metadata") or {}
        print(f"  best_score={meta.get('best_score')}, top_scores={len(out.get('top_scores') or [])}")
        # Verify NodeAnalysisRow
        db = sqlite3.connect(DB)
        row = db.execute(
            "SELECT tool_id, length(data) FROM node_analyses WHERE run_id=? AND tool_id='megadock'",
            (run["id"],)
        ).fetchone()
        db.close()
        if row:
            print(f"  NodeAnalysisRow: tool={row[0]}, bytes={row[1]}")
    RESULTS["megadock"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_dataset():
    print("\n═══ dataset ═══")
    # Use the "Please" dataset if it exists
    db = sqlite3.connect(DB)
    row = db.execute("SELECT id, name FROM datasets LIMIT 1").fetchone()
    db.close()
    if not row:
        print("  SKIP — no datasets in DB")
        RESULTS["dataset"] = None
        return

    dataset_id, dataset_name = row
    print(f"  using dataset: {dataset_name} ({dataset_id})")
    passed, run = run_test("TEST dataset", [
        {"id": "ds1", "tool": "dataset",
         "params": {"dataset_id": dataset_id},
         "position": {"x": 0, "y": 0}},
    ], timeout=60)
    if passed:
        out = run["nodes"].get("ds1", {}).get("outputs", {})
        print(f"  heavy_chain len={len(out.get('heavy_chain') or '')}, labels={len(out.get('labels') or [])}")
    RESULTS["dataset"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


# ─── BioPipelines tools ───────────────────────────────────────────────────────

def test_dna_encoder():
    print("\n═══ dna_encoder ═══")
    passed, run = run_test("TEST dna_encoder", [
        {"id": "dna1", "tool": "dna_encoder",
         "params": {"sequence": VH, "organism": "HS"},
         "position": {"x": 0, "y": 0}},
    ], timeout=60)
    if passed:
        out = run["nodes"].get("dna1", {}).get("outputs", {})
        seqs = out.get("dna_sequences", "")
        gc = out.get("gc_content", [])
        print(f"  dna_sequences: {len(seqs)} chars, gc_content entries: {len(gc)}")
    RESULTS["dna_encoder"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_fuse():
    print("\n═══ fuse ═══")
    passed, run = run_test("TEST fuse", [
        {"id": "fuse1", "tool": "fuse",
         "params": {
             "sequences": json.dumps(["VSKGEELFTG", "ADQLTEEQIA"]),
             "linker": "GSG",
             "linker_lengths": json.dumps(["0-2"]),
             "name": "test_fusion",
         },
         "position": {"x": 0, "y": 0}},
    ], timeout=60)
    if passed:
        out = run["nodes"].get("fuse1", {}).get("outputs", {})
        fusions = out.get("fusions", [])
        print(f"  fusions: {len(fusions)} variants")
        if fusions:
            print(f"  first: {fusions[0].get('id')} — {fusions[0].get('sequence')[:40]}...")
    RESULTS["fuse"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_mutation_profiler():
    print("\n═══ mutation_profiler ═══")
    mutants = [
        VH[:10] + "A" + VH[11:],   # Lys→Ala at pos 10
        VH[:20] + "R" + VH[21:],   # mutate pos 20
        VH,                         # same as original
    ]
    passed, run = run_test("TEST mutation_profiler", [
        {"id": "mp1", "tool": "mutation_profiler",
         "params": {"original": VH, "mutants": json.dumps(mutants)},
         "position": {"x": 0, "y": 0}},
    ], timeout=60)
    if passed:
        out = run["nodes"].get("mp1", {}).get("outputs", {})
        freq = out.get("absolute_frequencies", {})
        positions = len(freq) if isinstance(freq, dict) else 0
        print(f"  absolute_frequencies: {positions} positions profiled")
    RESULTS["mutation_profiler"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_mutation_composer():
    print("\n═══ mutation_composer ═══")
    # mutation_profiler feeds frequencies; original is passed as param to composer
    mutants = [VH[:10] + "A" + VH[11:], VH[:10] + "R" + VH[11:], VH]
    rid = submit("TEST mutation_composer setup", [
        {"id": "mp1", "tool": "mutation_profiler",
         "params": {"original": VH, "mutants": json.dumps(mutants)},
         "position": {"x": 0, "y": 0}},
        {"id": "mc1", "tool": "mutation_composer",
         "params": {"original": VH, "num_sequences": 3, "mode": "weighted_random", "max_mutations": 2},
         "position": {"x": 300, "y": 0}},
    ], edges=[
        {"source": "mp1.absolute_frequencies", "target": "mc1.frequencies"},
    ])
    print(f"  run_id: {rid}")
    run = poll(rid, timeout=90)
    passed = check_run(run, "mutation_composer")
    if passed:
        out = run["nodes"].get("mc1", {}).get("outputs", {})
        seqs = out.get("sequences", [])
        print(f"  sequences: {len(seqs)} candidates generated")
    RESULTS["mutation_composer"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_distance_selector():
    print("\n═══ distance_selector ═══")
    # Use a small fake PDB with a HETATM ligand for testing
    mini_pdb = (
        "ATOM      1  CA  ALA A   1       1.000   0.000   0.000  1.00 50.00           C\n"
        "ATOM      2  CA  GLY A   2       4.000   0.000   0.000  1.00 50.00           C\n"
        "ATOM      3  CA  VAL A   3       8.000   0.000   0.000  1.00 50.00           C\n"
        "HETATM    4  C1  LIG A 100       2.000   0.000   0.000  1.00 50.00           C\n"
        "END\n"
    )
    passed, run = run_test("TEST distance_selector", [
        {"id": "ds1", "tool": "distance_selector",
         "params": {"structure": mini_pdb, "ligand_name": "LIG", "distance_cutoff": 5.0},
         "position": {"x": 0, "y": 0}},
    ], timeout=60)
    if passed:
        out = run["nodes"].get("ds1", {}).get("outputs", {})
        sel = out.get("selections", {})
        within = sel.get("within", []) if isinstance(sel, dict) else sel
        n_res = sel.get("n_residues", len(within)) if isinstance(sel, dict) else len(within)
        print(f"  selections: {n_res} pocket residues within 5 Å")
        if within:
            print(f"  first: {within[0]}")
    RESULTS["distance_selector"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


def test_compound_library():
    print("\n═══ compound_library ═══")
    passed, run = run_test("TEST compound_library", [
        {"id": "cl1", "tool": "compound_library",
         "params": {"smiles_dict": json.dumps({
             "ibuprofen":   "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
             "aspirin":     "CC(=O)Oc1ccccc1C(=O)O",
             "paracetamol": "CC(=O)Nc1ccc(O)cc1",
         })},
         "position": {"x": 0, "y": 0}},
    ], timeout=60)
    if passed:
        out = run["nodes"].get("cl1", {}).get("outputs", {})
        compounds = out.get("compounds", [])
        print(f"  compounds: {len(compounds)} entries")
        for c in compounds[:3]:
            print(f"    {c.get('name')}: {c.get('smiles','')[:40]}")
    RESULTS["compound_library"] = passed
    print(f"  {'PASS ✓' if passed else 'FAIL ✗'}")


# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    group = sys.argv[1] if len(sys.argv) > 1 else "all"

    # Already-tested structure tools (from test_structure_tools.py):
    RESULTS["immunebuilder"]    = True
    RESULTS["equifold"]         = True
    RESULTS["alphafold_monomer"] = True
    RESULTS["equidock"]         = True

    if group in ("all", "inputs"):
        test_echo()
        test_sequence_input()
        test_target_input()
        test_sequence_db()
        test_compute()
        test_dataset()

    if group in ("all", "sequence"):
        test_ablang()
        test_esm_embedding()
        test_biophi()
        test_deepsp()
        test_netsolp()
        test_liability_scanner()

    if group in ("all", "design"):
        test_cdr_mutator()
        test_progen2()
        test_iglm()

    if group in ("all", "biopipelines"):
        test_dna_encoder()
        test_fuse()
        test_mutation_profiler()
        test_mutation_composer()
        test_distance_selector()
        test_compound_library()

    if group in ("all", "pipeline"):
        test_developability_filter()
        test_rank()
        test_filter()
        test_evaluate()
        test_choose()

    if group in ("all", "structure"):
        test_pdbfixer()
        test_superwater()

    if group in ("slow",):
        test_megadock()

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("RESULTS:")

    skipped   = [k for k, v in RESULTS.items() if v is None]
    passed    = [k for k, v in RESULTS.items() if v is True]
    failed    = [k for k, v in RESULTS.items() if v is False]
    inherited = [k for k, v in RESULTS.items() if v is True and k in
                 ("immunebuilder", "equifold", "alphafold_monomer", "equidock")]

    for name in sorted(RESULTS.keys()):
        v = RESULTS[name]
        icon = "✓" if v else ("—" if v is None else "✗")
        note = " (from structure tests)" if name in inherited else (" (SKIP)" if v is None else "")
        print(f"  {icon} {name}{note}")

    print(f"\n  Passed:  {len(passed)}/{len(RESULTS)}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    if failed:
        print(f"  FAILED:  {', '.join(failed)}")
    print()
    if not failed:
        print("ALL TESTS PASSED (or skipped)")
    else:
        print(f"FAILURES: {', '.join(failed)}")
