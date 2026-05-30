#!/usr/bin/env python3
"""End-to-end API tests for embedding tools.

Tests the full pipeline:
  1. Single-node ablang run (VH only, VH+VL, batch via sequences)
  2. Single-node esm_embedding run
  3. sequence_input → ablang (edge wiring)
  4. sequence_input → esm_embedding (edge wiring, legacy 'sequence' edge target)

Run: python3 tools/test_api_embedding.py
"""
import json
import sys
import time
import uuid

import urllib.request
import urllib.error

BASE = "http://localhost:8000"

VH = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISGSGGSTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAKDRLSITIRPRYYGLDVWGQGTLVTVSS"
VL = "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQSYSTPLTFGGGTKVEIK"
VH2 = "QVQLVQSGAEVKKPGSSVKVSCKASGGTFSSYAISWVRQAPGQGLEWMGGIIPIFGTANYAQKFQGRVTITADKSTSTAYMELSSLRSEDTAVYYCAR"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def api(method: str, path: str, body=None, expect=200):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        raise RuntimeError(f"{method} {path} → HTTP {e.code}: {detail}") from e


def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  FAIL  {msg}")
        sys.exit(1)
    print(f"  ok    {msg}")


def wait_for_run(run_id: str, timeout: int = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = api("GET", f"/api/runs/{run_id}/")
        status = run.get("status")
        if status in ("succeeded", "failed", "cancelled"):
            return run
        print(f"  ...{status}")
        time.sleep(3)
    raise RuntimeError(f"Run {run_id} did not finish within {timeout}s")


def create_and_run(pipeline: dict, label: str) -> dict:
    """Create a pipeline, start a run, wait for completion, return node outputs."""
    pipeline["id"] = f"test-{uuid.uuid4().hex[:8]}"

    created = api("POST", "/api/pipelines/", pipeline)
    pipeline_id = created["id"]
    # POST /api/runs/ expects a full Pipeline body (it snapshots what you send)
    full_pipeline = api("GET", f"/api/pipelines/{pipeline_id}/")
    stored_nodes = full_pipeline.get("nodes", [])
    print(f"\n--- {label} --- (pipeline={pipeline_id}, nodes={len(stored_nodes)})")
    if len(stored_nodes) == 0 and len(pipeline.get("nodes", [])) > 0:
        raise RuntimeError(f"Pipeline created with no nodes — check GET /api/pipelines/{pipeline_id}/")

    run = api("POST", "/api/runs/", full_pipeline)
    run_id = run["id"]
    print(f"  run {run_id} started")

    completed = wait_for_run(run_id)
    status = completed.get("status")
    print(f"  status: {status}")

    if status != "succeeded":
        nodes = completed.get("nodes") or {}
        for nid, ns in nodes.items():
            if ns.get("status") == "failed":
                print(f"  node {nid} error: {ns.get('error','')[:300]}")
        raise RuntimeError(f"Run failed: {label}")

    # outputs are at run["nodes"][node_id]["outputs"]
    raw_nodes = completed.get("nodes") or {}
    return {nid: ns.get("outputs", {}) for nid, ns in raw_nodes.items()}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_embedding_output(outputs: dict, node_id: str, label: str) -> None:
    out = outputs.get(node_id, {})
    check("n" in out,       f"[{label}] output has 'n'")
    check("results" in out, f"[{label}] output has 'results'")
    n = out["n"]
    results = out["results"]
    check(isinstance(n, int) and n > 0,           f"[{label}] n={n} is positive int")
    check(isinstance(results, list) and len(results) == n, f"[{label}] len(results)==n")
    for i, r in enumerate(results):
        check("vh" in r and "emb_vh" in r,      f"[{label}] results[{i}] has vh + emb_vh")
        check(isinstance(r["emb_vh"], list) and len(r["emb_vh"]) > 0,
              f"[{label}] emb_vh is non-empty")
        check(isinstance(r["emb_vh"][0], float), f"[{label}] emb_vh contains floats")
    # Standard batch token also emitted
    check("sequences" in out,           f"[{label}] output has 'sequences' batch token")
    seqs = out["sequences"]
    check(isinstance(seqs, dict) and "variants" in seqs,
          f"[{label}] sequences is {{n, variants}} token")
    check(len(seqs["variants"]) == n, f"[{label}] sequences.variants count matches n")
    print(f"  dim={len(results[0]['emb_vh'])}, "
          f"vl_embedded={results[0].get('emb_vl') is not None}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ablang_single_vh():
    pipeline = {
        "name": "test-ablang-vh-only",
        "schema_version": "1",
        "nodes": [{"id": "ab", "tool": "ablang",
                   "params": {"vh": VH, "mode": "seqcoding"}, "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "ablang single VH")
    validate_embedding_output(outputs, "ab", "ablang single VH")
    r = outputs["ab"]["results"][0]
    check(r["vl"] is None,     "vl=null for VH-only")
    check(r["emb_vl"] is None, "emb_vl=null for VH-only")
    print("ablang single VH: PASSED")


def test_ablang_pair():
    pipeline = {
        "name": "test-ablang-pair",
        "schema_version": "1",
        "nodes": [{"id": "ab", "tool": "ablang",
                   "params": {"vh": VH, "vl": VL, "mode": "seqcoding"},
                   "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "ablang VH+VL pair")
    validate_embedding_output(outputs, "ab", "ablang VH+VL pair")
    r = outputs["ab"]["results"][0]
    check(r["emb_vl"] is not None, "emb_vl populated")
    check(len(r["emb_vh"]) == len(r["emb_vl"]), "emb_vh/vl same dim")
    print("ablang VH+VL pair: PASSED")


def test_ablang_batch():
    pipeline = {
        "name": "test-ablang-batch",
        "schema_version": "1",
        "nodes": [{"id": "ab", "tool": "ablang",
                   "params": {"sequences": [{"vh": VH, "vl": VL},
                                             {"vh": VH2, "vl": None}],
                               "mode": "seqcoding"},
                   "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "ablang batch 2")
    validate_embedding_output(outputs, "ab", "ablang batch 2")
    check(outputs["ab"]["n"] == 2, "n=2")
    check(outputs["ab"]["results"][1]["emb_vl"] is None, "second entry VH-only")
    print("ablang batch: PASSED")


def test_esm_single_vh():
    pipeline = {
        "name": "test-esm-vh-only",
        "schema_version": "1",
        "nodes": [{"id": "esm", "tool": "esm_embedding",
                   "params": {"vh": VH, "model_size": "8M", "pool_mode": "mean"},
                   "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "esm single VH (8M)")
    validate_embedding_output(outputs, "esm", "esm single VH")
    check(outputs["esm"]["metadata"]["dim"] == 320, "8M dim=320")
    print("esm single VH: PASSED")


def test_esm_pair():
    pipeline = {
        "name": "test-esm-pair",
        "schema_version": "1",
        "nodes": [{"id": "esm", "tool": "esm_embedding",
                   "params": {"vh": VH, "vl": VL, "model_size": "8M", "pool_mode": "mean"},
                   "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "esm VH+VL pair (8M)")
    validate_embedding_output(outputs, "esm", "esm VH+VL pair")
    check(outputs["esm"]["results"][0]["emb_vl"] is not None, "emb_vl populated")
    print("esm VH+VL pair: PASSED")


def test_sequence_input_to_ablang():
    """Edge: sequence_input.heavy_chain → ablang.vh"""
    pipeline = {
        "name": "test-seqin-ablang",
        "schema_version": "1",
        "nodes": [
            {"id": "si",  "tool": "sequence_input",
             "params": {"heavy_chain": VH, "light_chain": VL},
             "position": {"x": 0, "y": 0}},
            {"id": "ab",  "tool": "ablang",
             "params": {"mode": "seqcoding"},
             "position": {"x": 300, "y": 0}},
        ],
        "edges": [
            {"source": "si.heavy_chain", "target": "ab.vh"},
            {"source": "si.light_chain", "target": "ab.vl"},
        ],
    }
    outputs = create_and_run(pipeline, "sequence_input → ablang (new edges)")
    validate_embedding_output(outputs, "ab", "seqin→ablang")
    r = outputs["ab"]["results"][0]
    check(r["emb_vl"] is not None, "emb_vl from wired VL")
    print("sequence_input → ablang: PASSED")


def test_legacy_sequence_edge_to_esm():
    """Backward compat: old 'sequence' edge target still works via legacy fallback."""
    pipeline = {
        "name": "test-legacy-esm",
        "schema_version": "1",
        "nodes": [
            {"id": "si",  "tool": "sequence_input",
             "params": {"heavy_chain": VH},
             "position": {"x": 0, "y": 0}},
            {"id": "esm", "tool": "esm_embedding",
             "params": {"model_size": "8M", "pool_mode": "mean"},
             "position": {"x": 300, "y": 0}},
        ],
        "edges": [
            # Old-style edge using removed 'sequence' input name
            {"source": "si.heavy_chain", "target": "esm.sequence"},
        ],
    }
    outputs = create_and_run(pipeline, "legacy 'sequence' edge → esm_embedding")
    validate_embedding_output(outputs, "esm", "legacy edge esm")
    print("legacy sequence edge → esm: PASSED")


def test_ablang_to_custom_dnn():
    """ablang output feeds custom_dnn via embedding_input (inference mode, no labels)."""
    pipeline = {
        "name": "test-ablang-dnn",
        "schema_version": "1",
        "nodes": [
            {"id": "ab",  "tool": "ablang",
             "params": {"vh": VH, "mode": "seqcoding"},
             "position": {"x": 0, "y": 0}},
            {"id": "dnn", "tool": "custom_dnn",
             "params": {
                 # No labels → inference-only forward pass (no training needed)
                 "architecture_spec": json.dumps({
                     "nodes": [
                         {"id": "in1",  "type": "Input",  "label": "Input",  "params": {}},
                         {"id": "fc1",  "type": "Linear", "label": "FC",
                          "params": {"in_features": 768, "out_features": 64}},
                         {"id": "relu", "type": "ReLU",   "label": "ReLU",   "params": {}},
                         {"id": "out",  "type": "Output", "label": "Output", "params": {}},
                     ],
                     "edges": [
                         {"source": "in1", "target": "fc1"},
                         {"source": "fc1", "target": "relu"},
                         {"source": "relu", "target": "out"},
                     ],
                 }),
             },
             "position": {"x": 300, "y": 0}},
        ],
        "edges": [
            {"source": "ab.results",  "target": "dnn.embedding_input"},
        ],
    }
    outputs = create_and_run(pipeline, "ablang → custom_dnn")
    dnn_out = outputs.get("dnn", {})
    check("predictions" in dnn_out or "metrics" in dnn_out or "error" not in dnn_out,
          "custom_dnn ran without fatal error")
    print("ablang → custom_dnn: PASSED")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TESTS = [
    ("ablang_single_vh",       test_ablang_single_vh),
    ("ablang_pair",            test_ablang_pair),
    ("ablang_batch",           test_ablang_batch),
    ("esm_single_vh",          test_esm_single_vh),
    ("esm_pair",               test_esm_pair),
    ("sequence_input_ablang",  test_sequence_input_to_ablang),
    ("legacy_sequence_edge",   test_legacy_sequence_edge_to_esm),
    ("ablang_to_custom_dnn",   test_ablang_to_custom_dnn),
]

if __name__ == "__main__":
    requested = sys.argv[1:] or [name for name, _ in TESTS]
    print(f"Running {len(requested)} test(s) against {BASE}\n")

    passed, failed = [], []
    for name, fn in TESTS:
        if name not in requested:
            continue
        try:
            fn()
            passed.append(name)
        except (RuntimeError, AssertionError, SystemExit) as e:
            print(f"  ERROR: {e}")
            failed.append(name)

    print(f"\n{'='*50}")
    print(f"Passed: {len(passed)}  Failed: {len(failed)}")
    if failed:
        print("Failed:", ", ".join(failed))
        sys.exit(1)
    print("All tests passed.")
