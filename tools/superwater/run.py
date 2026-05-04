#!/usr/bin/env python3
"""SuperWater subprocess entry point.

Reads JSON from stdin, writes JSON to stdout.
Progress lines go to stderr → forwarded live to the UI terminal.

Mirrors the webapp/app.py pipeline exactly:
  1. organize_pdb_dataset.py — normalise chains, create split file
  2. esm_embedding_preparation_water.py — build FASTA
  3. esm/scripts/extract.py — ESM2 embeddings (runs in data/ cwd)
  4. python -m inference_water_pos — diffusion inference
  5. Read centroid PDB, return as hydrated_structure
"""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _run(cmd: list, cwd: str, env: dict, label: str) -> None:
    """Run a command, stream its output to stderr."""
    _progress(f"[{label}] {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _progress(line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"[{label}] failed with exit code {proc.returncode}")


def _find_repo() -> Path:
    tool_dir = Path(__file__).resolve().parent
    candidate = tool_dir / "SuperWater"
    if not (candidate / "inference_water_pos.py").exists():
        raise RuntimeError(
            "SuperWater repo not found. Run: bash tools/superwater/setup.sh"
        )
    return candidate


def _find_python() -> str:
    conda_roots = [
        os.path.expanduser("~/miniforge3"),
        os.path.expanduser("~/mambaforge"),
        os.path.expanduser("~/miniconda3"),
        os.path.expanduser("~/anaconda3"),
    ]
    for root in conda_roots:
        py = Path(root) / "envs" / "superwater" / "bin" / "python"
        if py.exists():
            return str(py)
    raise RuntimeError(
        "No superwater conda env found. Run: bash tools/superwater/setup.sh"
    )


def main() -> None:
    inputs = json.load(sys.stdin)

    pdb_text    = inputs.get("structure", "")
    water_ratio = str(inputs.get("water_ratio", 1.0))
    cap         = str(inputs.get("cap", 0.1))

    if not pdb_text or "ATOM" not in pdb_text:
        print(json.dumps({"error": "structure input is empty or contains no ATOM records"}))
        sys.exit(1)

    repo  = _find_repo()
    python = _find_python()

    # Unique run-scoped directory names to allow concurrent runs
    run_id   = uuid.uuid4().hex[:8]
    raw_name = f"sw{run_id}"    # e.g. sw3f7a2c1b
    pdb_id   = "prot"           # 4-char PDB ID used throughout
    org_name = f"{raw_name}_organized"

    env = {**os.environ, "PYTHONPATH": str(repo), "PYTHONUNBUFFERED": "1"}

    # Directories (all relative to repo root, as the scripts expect)
    raw_dir = repo / "data" / raw_name
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Initialize cleanup vars before try so finally block can reference them safely
    emb_out  = f"{org_name}_embeddings_output"
    # inference_water_pos hardcodes output to inference_out/inferenced_pos_rr{ratio*steps}_cap{cap}/
    # water_ratio * resample_steps (default 1) = water_ratio
    pred_dir = f"inferenced_pos_rr{water_ratio}_cap{cap}"

    # Step 0: write input PDB
    (raw_dir / f"{pdb_id}.pdb").write_text(pdb_text)
    _progress(f"SuperWater [0/4]: wrote input PDB as {pdb_id}.pdb in {raw_dir}")

    try:
        # Step 1: organise
        _progress(f"SuperWater [1/4]: organising dataset {raw_name}…")
        _run(
            [python, "organize_pdb_dataset.py",
             "--raw_data",       raw_name,
             "--data_root",      "data",
             "--output_dir",     org_name,
             "--splits_path",    "data/splits",
             "--dummy_water_dir","data/dummy_water",
             "--logs_dir",       "logs"],
            cwd=str(repo), env=env, label="organize",
        )

        # Step 2: prepare FASTA for ESM
        _progress("SuperWater [2/4]: preparing ESM FASTA…")
        fasta_file = f"prepared_for_esm_{org_name}.fasta"
        _run(
            [python, "datasets/esm_embedding_preparation_water.py",
             "--data_dir", f"data/{org_name}",
             "--out_file",  f"data/{fasta_file}"],
            cwd=str(repo), env=env, label="esm_prep",
        )

        # Step 3: ESM2 embeddings — must run from data/ with relative paths
        _progress("SuperWater [3/4]: computing ESM2 embeddings (downloads ~650M model on first run)…")
        esm_extract = repo / "esm" / "scripts" / "extract.py"
        _run(
            [python, str(esm_extract),
             "esm2_t33_650M_UR50D",
             fasta_file,
             emb_out,
             "--repr_layers", "33",
             "--include", "per_tok",
             "--truncation_seq_length", "4096"],
            cwd=str(repo / "data"), env=env, label="esm_extract",
        )

        # Step 4: inference
        # Output goes to inference_out/inferenced_pos_rr{ratio}_cap{cap}/ (hardcoded in script)
        _progress(f"SuperWater [4/4]: running diffusion inference (ratio={water_ratio}, cap={cap})…")
        _run(
            [python, "-m", "inference_water_pos",
             "--original_model_dir", "workdir/all_atoms_score_model_res15_17092",
             "--confidence_dir",     "workdir/confidence_model_17092_sigmoid_rr15",
             "--data_dir",           f"data/{org_name}",
             "--ckpt",               "best_model.pt",
             "--all_atoms",
             "--cache_path",         "data/cache_confidence",
             "--split_test",         f"data/splits/{org_name}.txt",
             "--inference_steps",    "20",
             "--esm_embeddings_path", f"data/{emb_out}",
             "--cap",                cap,
             "--running_mode",       "test",
             "--mad_prediction",
             "--save_pos",
             "--water_ratio",        water_ratio],
            cwd=str(repo), env=env, label="inference",
        )

        # Find output — inference writes to inference_out/<pred_dir>/<pdb_id>/<pdb_id>_centroid.pdb
        centroid = repo / "inference_out" / pred_dir / pdb_id / f"{pdb_id}_centroid.pdb"
        if not centroid.exists():
            # Fallback: any PDB in that directory
            candidates = sorted((repo / "inference_out" / pred_dir).rglob("*.pdb"))
            if not candidates:
                raise RuntimeError(
                    f"No output PDB found in inference_out/{pred_dir}. "
                    f"Check the inference log above for errors."
                )
            centroid = candidates[0]

        hydrated_pdb = centroid.read_text()
        water_lines  = [l for l in hydrated_pdb.splitlines() if "HOH" in l and l.startswith("HETATM")]
        n_waters     = len(water_lines)
        _progress(f"SuperWater: placed {n_waters} water molecules")

        print(json.dumps({
            "hydrated_structure": hydrated_pdb,
            "water_count": {"waters_placed": n_waters, "cap": float(cap), "water_ratio": float(water_ratio)},
        }))

    finally:
        # Clean up run-specific dirs to avoid accumulation
        for d in [raw_dir, repo / "data" / org_name]:
            shutil.rmtree(str(d), ignore_errors=True)
        for p in [
            repo / "data" / f"prepared_for_esm_{org_name}.fasta",
            repo / "data" / "splits" / f"{org_name}.txt",
        ]:
            p.unlink(missing_ok=True)
        # Remove embeddings (can be large)
        shutil.rmtree(str(repo / "data" / emb_out), ignore_errors=True)  # type: ignore[possibly-undefined]
        # Keep inference_out for debugging; remove on next run if needed


if __name__ == "__main__":
    main()
