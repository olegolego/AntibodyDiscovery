#!/usr/bin/env python3
"""Validates the standard embedding output format for ablang and esm_embedding.

Run with the tool's own venv:
  tools/ablang/.venv/bin/python tools/test_embedding_format.py ablang
  tools/esm_embedding/.venv/bin/python tools/test_embedding_format.py esm

Or run both with the backend venv (for the adapter parse_sequences tests):
  .venv/bin/python tools/test_embedding_format.py adapter
"""
import json
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"  FAIL: {msg}")
        sys.exit(1)
    print(f"  OK:   {msg}")


def validate_standard_output(out: dict, label: str) -> None:
    print(f"\n--- {label} ---")
    check("n" in out,       "output has 'n' key")
    check("results" in out, "output has 'results' key")
    n = out["n"]
    results = out["results"]
    check(isinstance(n, int) and n > 0,       f"n={n} is a positive int")
    check(isinstance(results, list),           "results is a list")
    check(len(results) == n,                   f"len(results)==n ({len(results)}=={n})")
    for i, r in enumerate(results):
        check("vh"     in r, f"results[{i}] has 'vh'")
        check("vl"     in r, f"results[{i}] has 'vl'")
        check("emb_vh" in r, f"results[{i}] has 'emb_vh'")
        check("emb_vl" in r, f"results[{i}] has 'emb_vl'")
        check(isinstance(r["emb_vh"], list) and len(r["emb_vh"]) > 0,
              f"results[{i}].emb_vh is non-empty list")
        check(isinstance(r["emb_vh"][0], float),
              f"results[{i}].emb_vh contains floats")
    print(f"  dim={len(results[0]['emb_vh'])}, vl_embedded={results[0]['emb_vl'] is not None}")


def run_subprocess(tool_id: str, inputs: dict) -> dict:
    python = TOOLS_DIR / tool_id / ".venv" / "bin" / "python"
    runner = TOOLS_DIR / tool_id / "run.py"
    proc = subprocess.run(
        [str(python), str(runner)],
        input=json.dumps(inputs).encode(),
        capture_output=True,
        timeout=600,
    )
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout).get("error", "")
        except Exception:
            err = proc.stderr.decode()[-1000:]
        print(f"FAIL: {tool_id} exited {proc.returncode}: {err}")
        sys.exit(1)
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------

VH = "EVQLVESGGGLVQPGGSLRLSCAASGFTFSSYAMSWVRQAPGKGLEWVSAISGSGGSTYYADSVKGRFTISRDNSKNTLYLQMNSLRAEDTAVYYCAKDRLSITIRPRYYGLDVWGQGTLVTVSS"
VL = "DIQMTQSPSSLSASVGDRVTITCRASQSISSYLNWYQQKPGKAPKLLIYAASSLQSGVPSRFSGSGSGTDFTLTISSLQPEDFATYYCQQSYSTPLTFGGGTKVEIK"
VH2 = "QVQLVQSGAEVKKPGSSVKVSCKASGGTFSSYAISWVRQAPGQGLEWMGGIIPIFGTANYAQKFQGRVTITADKSTSTAYMELSSLRSEDTAVYYCAR"


def test_ablang() -> None:
    print("\n=== AbLang ===")

    # Single VH only
    out = run_subprocess("ablang", {"vh": VH, "mode": "seqcoding"})
    validate_standard_output(out, "single VH")
    check(out["results"][0]["vl"] is None, "vl is null for VH-only input")
    check(out["results"][0]["emb_vl"] is None, "emb_vl is null for VH-only input")

    # Single VH + VL pair
    out = run_subprocess("ablang", {"vh": VH, "vl": VL, "mode": "seqcoding"})
    validate_standard_output(out, "VH+VL pair")
    check(out["results"][0]["emb_vl"] is not None, "emb_vl populated when VL provided")
    check(len(out["results"][0]["emb_vh"]) == len(out["results"][0]["emb_vl"]),
          "emb_vh and emb_vl have same dim")

    # Batch of two pairs via sequences field
    out = run_subprocess("ablang", {
        "sequences": [{"vh": VH, "vl": VL}, {"vh": VH2, "vl": None}],
        "mode": "seqcoding",
    })
    validate_standard_output(out, "batch of 2")
    check(out["n"] == 2, "n=2 for batch of 2")
    check(out["results"][1]["emb_vl"] is None, "second entry has no emb_vl")

    print("\nAbLang: ALL TESTS PASSED")


def test_esm() -> None:
    print("\n=== ESM2 ===")

    # Single VH only (small model for speed)
    out = run_subprocess("esm_embedding", {"vh": VH, "model_size": "8M", "pool_mode": "mean"})
    validate_standard_output(out, "single VH (8M, mean)")
    check(out["results"][0]["vl"] is None, "vl is null for VH-only input")
    check(out["metadata"]["dim"] == 320, "8M model dim=320")

    # Single VH + VL
    out = run_subprocess("esm_embedding", {"vh": VH, "vl": VL, "model_size": "8M", "pool_mode": "mean"})
    validate_standard_output(out, "VH+VL pair (8M, mean)")
    check(out["results"][0]["emb_vl"] is not None, "emb_vl populated when VL provided")

    # Batch via sequences
    out = run_subprocess("esm_embedding", {
        "sequences": [{"vh": VH, "vl": VL}, {"vh": VH2}],
        "model_size": "8M",
        "pool_mode": "mean",
    })
    validate_standard_output(out, "batch of 2 (8M, mean)")
    check(out["n"] == 2, "n=2")

    print("\nESM2: ALL TESTS PASSED")


def test_adapter_parse() -> None:
    """Test parse_sequences without needing ML packages."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.tools.embedding_utils import parse_sequences

    print("\n=== parse_sequences ===")

    # New standard
    r = parse_sequences({"sequences": [{"vh": VH, "vl": VL}]})
    check(len(r) == 1 and r[0]["vh"] == VH, "sequences list passthrough")

    # Legacy heavy_chain/light_chain
    r = parse_sequences({"heavy_chain": VH, "light_chain": VL})
    check(len(r) == 1 and r[0]["vl"] == VL, "heavy_chain/light_chain")

    # Legacy sequence
    r = parse_sequences({"sequence": VH})
    check(len(r) == 1 and r[0]["vh"] == VH and r[0]["vl"] is None, "single sequence field")

    # candidate_sequences
    r = parse_sequences({"candidate_sequences": [VH, VH2]})
    check(len(r) == 2 and r[1]["vh"] == VH2, "candidate_sequences list")

    # Multi-FASTA
    fasta = f">ab1\n{VH}\n>ab2\n{VH2}"
    r = parse_sequences({"heavy_chain": fasta})
    check(len(r) == 2, "multi-FASTA parsed into 2 entries")

    print("\nparse_sequences: ALL TESTS PASSED")


def test_normalizers() -> None:
    """Test _coerce_embeddings and _normalize_embedding_input with new format."""
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.tools.adapters.rcc_mlde import _coerce_embeddings
    from app.tools.adapters.custom_dnn import _normalize_embedding_input

    print("\n=== normalizers ===")
    fake_emb = [0.1, 0.2, 0.3]
    std_output = {
        "n": 2,
        "results": [
            {"vh": VH, "vl": VL, "emb_vh": fake_emb, "emb_vl": [0.4, 0.5, 0.6]},
            {"vh": VH2, "vl": None, "emb_vh": [0.7, 0.8, 0.9], "emb_vl": None},
        ],
    }

    coerced = _coerce_embeddings(std_output)
    check(coerced is not None, "_coerce_embeddings handles standard format")
    check(len(coerced) == 2, "_coerce_embeddings returns 2 entries")
    check(VH in coerced, "_coerce_embeddings keys by vh sequence")

    normalized = _normalize_embedding_input(std_output)
    check(normalized is not None, "_normalize_embedding_input handles standard format")
    check(len(normalized) == 2, "_normalize_embedding_input returns 2 entries")

    print("\nnormalizers: ALL TESTS PASSED")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SUITES = {
    "ablang":  test_ablang,
    "esm":     test_esm,
    "adapter": test_adapter_parse,
    "norm":    test_normalizers,
    "all":     None,
}

if __name__ == "__main__":
    suite = sys.argv[1] if len(sys.argv) > 1 else "all"
    if suite not in SUITES:
        print(f"Usage: {sys.argv[0]} [{' | '.join(SUITES)}]")
        sys.exit(1)

    if suite == "all":
        test_adapter_parse()
        test_normalizers()
        print("\n\nAll adapter/normalizer tests passed.")
        print("Run with tool venvs for ablang/esm tests:")
        print("  tools/ablang/.venv/bin/python tools/test_embedding_format.py ablang")
        print("  tools/esm_embedding/.venv/bin/python tools/test_embedding_format.py esm")
    else:
        SUITES[suite]()
