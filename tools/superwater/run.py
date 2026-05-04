#!/usr/bin/env python3
"""SuperWater subprocess entry point.

Reads JSON from stdin, writes JSON to stdout.
Progress lines go to stderr → forwarded live to the UI terminal.

Pipeline (mirrors the SuperWater repo):
  1. Write input PDB to temp dir
  2. Run organize_protein.py → normalise chains / residue numbering
  3. Run esm_embeddings.py → ESM2 embeddings for each residue
  4. Run inference_water_pos.py → place waters
  5. Read centroid output PDB, return as hydrated_structure
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _run(cmd: list[str], cwd: str, env: dict) -> None:
    """Run a subprocess, stream stdout+stderr to our stderr."""
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, text=True,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        _progress(line.rstrip())
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed (exit {proc.returncode}): {' '.join(cmd)}")


def _find_repo() -> Path:
    """Locate the cloned SuperWater repo next to this tool dir."""
    tool_dir = Path(__file__).resolve().parent
    candidate = tool_dir / "SuperWater"
    if not candidate.exists():
        raise RuntimeError(
            "SuperWater repo not found. Run: bash tools/superwater/setup.sh"
        )
    return candidate


def _find_python() -> str:
    """Return the conda env python or venv python, whichever was set up."""
    tool_dir = Path(__file__).resolve().parent

    # Prefer conda env
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

    # Fallback: .venv next to this file
    venv_py = tool_dir / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)

    raise RuntimeError(
        "No superwater Python environment found. Run: bash tools/superwater/setup.sh"
    )


def main() -> None:
    inputs = json.load(sys.stdin)

    pdb_text    = inputs.get("structure", "")
    water_ratio = float(inputs.get("water_ratio", 1.0))
    cap         = float(inputs.get("cap", 0.1))

    if not pdb_text or "ATOM" not in pdb_text:
        print(json.dumps({"error": "structure input is empty or contains no ATOM records"}))
        sys.exit(1)

    repo_dir = _find_repo()
    python   = _find_python()

    with tempfile.TemporaryDirectory(prefix="superwater_") as tmpdir:
        tmp = Path(tmpdir)

        # Write input PDB
        pdb_name = "input"
        raw_pdb  = tmp / f"{pdb_name}.pdb"
        raw_pdb.write_text(pdb_text)

        # Copy workdir (model weights) — symlink if large
        repo_workdir = repo_dir / "workdir"
        local_workdir = tmp / "workdir"
        if repo_workdir.exists():
            os.symlink(str(repo_workdir), str(local_workdir))

        # Setup env — forward PATH so conda shims work
        env = {**os.environ, "PYTHONPATH": str(repo_dir)}

        # Step 1: organise
        _progress(f"SuperWater [1/3]: organising protein {pdb_name}…")
        organised_dir = tmp / "organised"
        organised_dir.mkdir()
        _run(
            [python, str(repo_dir / "organize_protein.py"),
             "--input_dir", str(tmp),
             "--output_dir", str(organised_dir)],
            cwd=str(repo_dir), env=env,
        )

        # organised outputs land in organised_dir/<pdb_name>/<pdb_name>_organised.pdb
        # or directly as <pdb_name>.pdb — find it
        organised_pdb_candidates = list(organised_dir.rglob("*.pdb"))
        if not organised_pdb_candidates:
            raise RuntimeError("organize_protein.py produced no PDB output")
        organised_pdb = organised_pdb_candidates[0]

        # Step 2: ESM embeddings
        _progress("SuperWater [2/3]: computing ESM2 embeddings…")
        emb_dir = tmp / "embeddings"
        emb_dir.mkdir()
        _run(
            [python, str(repo_dir / "esm_embeddings.py"),
             "--input_dir", str(organised_dir),
             "--output_dir", str(emb_dir)],
            cwd=str(repo_dir), env=env,
        )

        # Step 3: inference
        _progress(f"SuperWater [3/3]: placing waters (ratio={water_ratio}, cap={cap})…")
        out_dir = tmp / "inference_out"
        out_dir.mkdir()
        _run(
            [python, str(repo_dir / "inference_water_pos.py"),
             "--protein_dir",    str(organised_dir),
             "--embedding_dir",  str(emb_dir),
             "--output_dir",     str(out_dir),
             "--water_ratio",    str(water_ratio),
             "--cap",            str(cap)],
            cwd=str(repo_dir), env=env,
        )

        # Find centroid PDB output
        centroid_pdbs = sorted(out_dir.rglob("*_centroid.pdb"))
        if not centroid_pdbs:
            # Fallback: any PDB in out_dir
            centroid_pdbs = sorted(out_dir.rglob("*.pdb"))
        if not centroid_pdbs:
            raise RuntimeError("SuperWater produced no output PDB")

        hydrated_pdb = centroid_pdbs[0].read_text()

        # Count HOH records
        water_lines = [l for l in hydrated_pdb.splitlines() if "HOH" in l and l.startswith("HETATM")]
        n_waters = len(water_lines)
        _progress(f"SuperWater: placed {n_waters} water molecules")

        print(json.dumps({
            "hydrated_structure": hydrated_pdb,
            "water_count": {"waters_placed": n_waters, "cap": cap, "water_ratio": water_ratio},
        }))


if __name__ == "__main__":
    main()
