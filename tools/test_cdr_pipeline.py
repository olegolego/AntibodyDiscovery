#!/usr/bin/env python3
"""End-to-end test: sequence_input → cdr_mutator → cheap_embedding → developability_filter.

Tests:
  1. CDR mutator output has n, sequences batch token, vl=None when no light chain
  2. CDR mutator sequences passes cleanly to cheap_embedding via the batch token
  3. cheap_embedding sequences batch token wires to developability_filter
  4. Full pipeline runs end to end

Run: python3 tools/test_cdr_pipeline.py
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


def api(method, path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} → HTTP {e.code}: {e.read().decode()}") from e


def check(cond, msg):
    if not cond:
        print(f"  FAIL  {msg}")
        sys.exit(1)
    print(f"  ok    {msg}")


def wait_for_run(run_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = api("GET", f"/api/runs/{run_id}/")
        status = run.get("status")
        if status in ("succeeded", "failed", "cancelled"):
            return run
        print(f"  ...{status}")
        time.sleep(3)
    raise RuntimeError(f"Run {run_id} timed out")


def create_and_run(pipeline, label):
    pipeline["id"] = f"test-{uuid.uuid4().hex[:8]}"
    created = api("POST", "/api/pipelines/", pipeline)
    pipeline_id = created["id"]
    full = api("GET", f"/api/pipelines/{pipeline_id}/")
    print(f"\n--- {label} --- (pipeline={pipeline_id})")
    run = api("POST", "/api/runs/", full)
    run_id = run["id"]
    print(f"  run {run_id} started")
    completed = wait_for_run(run_id)
    status = completed.get("status")
    print(f"  status: {status}")
    if status != "succeeded":
        nodes = completed.get("nodes") or {}
        for nid, ns in nodes.items():
            if ns.get("status") == "failed":
                print(f"  node {nid} error: {ns.get('error','')[:500]}")
        raise RuntimeError(f"Run failed: {label}")
    return {nid: ns.get("outputs", {}) for nid, ns in (completed.get("nodes") or {}).items()}


# ── Test 1: CDR mutator standalone — check output format ─────────────────────

def test_cdr_mutator_output_format():
    """CDR mutator emits n at top level, sequences batch token, vl=None for VH-only."""
    pipeline = {
        "name": "test-cdr-format",
        "schema_version": "1",
        "nodes": [{"id": "cdr", "tool": "cdr_mutator",
                   "params": {"heavy_chain": VH, "num_variants": 3, "strategy": "blosum62"},
                   "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "CDR mutator format check (VH-only)")
    out = outputs.get("cdr", {})

    check("n" in out, "top-level n")
    check(isinstance(out["n"], int) and out["n"] > 0, f"n={out['n']} is positive int")
    check("sequences" in out, "sequences batch token present")

    seqs = out["sequences"]
    check(isinstance(seqs, dict) and "variants" in seqs, "sequences is {n, variants}")
    check(seqs.get("n") == out["n"], "sequences.n == top-level n")

    variants = seqs["variants"]
    check(len(variants) == out["n"], "variants count matches n")
    for i, v in enumerate(variants):
        check("vh" in v, f"variant[{i}] has vh")
        check(v.get("vl") is None, f"variant[{i}] vl=None for VH-only")
    print("CDR mutator format: PASSED")


def test_cdr_mutator_pair_format():
    """With both chains: vl is populated in each variant."""
    pipeline = {
        "name": "test-cdr-pair",
        "schema_version": "1",
        "nodes": [{"id": "cdr", "tool": "cdr_mutator",
                   "params": {"heavy_chain": VH, "light_chain": VL,
                               "num_variants": 2, "cdr_l1": True, "strategy": "blosum62"},
                   "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    outputs = create_and_run(pipeline, "CDR mutator VH+VL pair format")
    out = outputs["cdr"]
    check(out["n"] >= 2, f"n >= 2 (got {out['n']})")
    variants = out["sequences"]["variants"]
    check(any(v.get("vl") for v in variants), "at least one variant has vl")
    print("CDR mutator pair format: PASSED")


# ── Test 2: sequence_input → cdr_mutator ─────────────────────────────────────

def test_sequence_input_to_cdr():
    """sequence_input.heavy_chain → cdr_mutator.heavy_chain — wiring works."""
    pipeline = {
        "name": "test-si-cdr",
        "schema_version": "1",
        "nodes": [
            {"id": "si",  "tool": "sequence_input",
             "params": {"heavy_chain": VH}, "position": {"x": 0, "y": 0}},
            {"id": "cdr", "tool": "cdr_mutator",
             "params": {"num_variants": 2, "strategy": "blosum62"},
             "position": {"x": 300, "y": 0}},
        ],
        "edges": [{"source": "si.heavy_chain", "target": "cdr.heavy_chain"}],
    }
    outputs = create_and_run(pipeline, "sequence_input → cdr_mutator")
    out = outputs["cdr"]
    check(out.get("n", 0) >= 2, f"cdr generated n={out.get('n')} variants")
    check("sequences" in out, "cdr has sequences batch token")
    print("sequence_input → cdr_mutator: PASSED")


# ── Test 3: cdr_mutator → cheap_embedding ────────────────────────────────────

def test_cdr_to_cheap():
    """CDR sequences batch token flows through parse_sequences to cheap_embedding."""
    pipeline = {
        "name": "test-cdr-cheap",
        "schema_version": "1",
        "nodes": [
            {"id": "cdr",  "tool": "cdr_mutator",
             "params": {"heavy_chain": VH, "num_variants": 2, "strategy": "blosum62"},
             "position": {"x": 0, "y": 0}},
            {"id": "emb",  "tool": "cheap_embedding",
             "params": {"shorten_factor": 1, "dim": 64},
             "position": {"x": 300, "y": 0}},
        ],
        "edges": [{"source": "cdr.sequences", "target": "emb.sequences"}],
    }
    outputs = create_and_run(pipeline, "cdr_mutator → cheap_embedding")
    out = outputs["emb"]
    check("n" in out, "cheap output has n")
    check(out["n"] == 2, f"cheap embedded 2 sequences (got {out['n']})")
    check("results" in out, "cheap output has results")
    check("sequences" in out, "cheap output has sequences batch token")
    r = out["results"][0]
    check("emb_vh" in r and isinstance(r["emb_vh"], list), "emb_vh is float list")
    print("cdr_mutator → cheap_embedding: PASSED")


# ── Test 4: full pipeline ─────────────────────────────────────────────────────

def test_full_pipeline():
    """sequence_input → cdr_mutator → cheap_embedding → developability_filter."""
    pipeline = {
        "name": "test-full-pipeline",
        "schema_version": "1",
        "nodes": [
            {"id": "si",  "tool": "sequence_input",
             "params": {"heavy_chain": VH}, "position": {"x": 0, "y": 0}},
            {"id": "cdr", "tool": "cdr_mutator",
             "params": {"num_variants": 3, "strategy": "blosum62"},
             "position": {"x": 300, "y": 0}},
            {"id": "emb", "tool": "cheap_embedding",
             "params": {"shorten_factor": 1, "dim": 64},
             "position": {"x": 600, "y": 0}},
            {"id": "dev", "tool": "developability_filter",
             "params": {}, "position": {"x": 900, "y": 0}},
        ],
        "edges": [
            {"source": "si.heavy_chain",  "target": "cdr.heavy_chain"},
            {"source": "cdr.sequences",   "target": "emb.sequences"},
            {"source": "emb.sequences",   "target": "dev.sequences"},
        ],
    }
    outputs = create_and_run(pipeline, "full pipeline: si → cdr → cheap → dev")

    # Check cdr output
    cdr = outputs["cdr"]
    check(cdr.get("n", 0) >= 3, f"cdr n={cdr.get('n')}")

    # Check cheap output
    emb = outputs["emb"]
    check(emb.get("n") == 3, f"cheap embedded n=3 (got {emb.get('n')})")
    check("sequences" in emb, "cheap has sequences token")

    # Check developability output
    dev = outputs["dev"]
    check("n_feasible" in dev, "developability has n_feasible")
    n_feas = dev["n_feasible"]
    check(isinstance(n_feas, int), f"n_feasible is int ({n_feas})")
    check("liability_report" in dev, "liability_report present")
    print(f"  developability: {n_feas}/3 passed")
    print("Full pipeline: PASSED")


TESTS = [
    ("cdr_format",          test_cdr_mutator_output_format),
    ("cdr_pair_format",     test_cdr_mutator_pair_format),
    ("seq_input_to_cdr",    test_sequence_input_to_cdr),
    ("cdr_to_cheap",        test_cdr_to_cheap),
    ("full_pipeline",       test_full_pipeline),
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
