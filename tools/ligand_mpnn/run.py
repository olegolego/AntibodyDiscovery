#!/usr/bin/env python3
"""LigandMPNN subprocess entry point.

Wraps the real LigandMPNN CLI (dauparas/LigandMPNN on GitHub).
Reads JSON from stdin, writes JSON to stdout, progress to stderr.

Install:  bash tools/ligand_mpnn/setup.sh
Repo:     https://github.com/dauparas/LigandMPNN
Paper:    Dauparas et al. 2025, Nat. Methods — doi:10.1038/s41592-024-02487-0
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_TOOL_DIR = Path(__file__).parent
_SRC_DIR = Path(os.getenv("LIGAND_MPNN_SRC", str(_TOOL_DIR / "src")))
_VENV_PYTHON = _TOOL_DIR / ".venv" / "bin" / "python"


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _parse_redesigned(redesigned) -> list[str]:
    """Convert [{chain, resnum}] → ['A1', 'A5', ...] for LigandMPNN --redesigned_residues."""
    if not redesigned:
        return []
    if isinstance(redesigned, str):
        try:
            redesigned = json.loads(redesigned)
        except Exception:
            return []
    result = []
    for r in redesigned:
        if isinstance(r, dict):
            chain = r.get("chain", "A")
            resnum = r.get("resnum", 1)
            result.append(f"{chain}{resnum}")
    return result


def _parse_fasta_dir(seqs_dir: Path) -> tuple[list[str], list[float]]:
    """Parse FASTA files output by LigandMPNN → (sequences, scores)."""
    sequences: list[str] = []
    scores: list[float] = []
    for fasta_path in sorted(seqs_dir.glob("*.fasta")):
        content = fasta_path.read_text()
        current_header = ""
        current_seq_lines: list[str] = []
        for line in content.splitlines():
            if line.startswith(">"):
                if current_seq_lines:
                    sequences.append("".join(current_seq_lines))
                    scores.append(_extract_score(current_header))
                current_header = line[1:]
                current_seq_lines = []
            else:
                current_seq_lines.append(line.strip())
        if current_seq_lines:
            sequences.append("".join(current_seq_lines))
            scores.append(_extract_score(current_header))
    return sequences, scores


def _extract_score(header: str) -> float:
    for part in header.split(","):
        part = part.strip()
        if "overall_confidence=" in part:
            try:
                return float(part.split("=")[1])
            except (ValueError, IndexError):
                pass
        if "seq_rec=" in part:
            try:
                return float(part.split("=")[1])
            except (ValueError, IndexError):
                pass
    return -1.0


def _run(inputs: dict) -> dict:
    structure: str = inputs.get("structure", "")
    num_sequences: int = int(inputs.get("num_sequences", 10))
    redesigned = inputs.get("redesigned", [])
    sampling_temp: float = float(inputs.get("sampling_temp", 0.1))

    if not structure:
        raise ValueError("structure (PDB text) is required")
    if not _SRC_DIR.exists():
        raise RuntimeError(
            f"LigandMPNN source not found at {_SRC_DIR}. "
            "Run:  bash tools/ligand_mpnn/setup.sh"
        )

    redesigned_residues = _parse_redesigned(redesigned)
    python = str(_VENV_PYTHON) if _VENV_PYTHON.exists() else sys.executable
    run_py = _SRC_DIR / "run.py"

    with tempfile.TemporaryDirectory() as tmpdir:
        pdb_path = Path(tmpdir) / "input.pdb"
        pdb_path.write_text(structure)
        out_dir = Path(tmpdir) / "output"
        out_dir.mkdir()

        cmd = [
            python, str(run_py),
            "--pdb_path", str(pdb_path),
            "--out_folder", str(out_dir),
            "--number_of_batches", str(num_sequences),
            "--temperature", str(sampling_temp),
            "--model_type", "ligand_mpnn",
            "--seed", "111",
        ]
        if redesigned_residues:
            cmd += ["--redesigned_residues", " ".join(redesigned_residues)]

        _progress(
            f"Running LigandMPNN: {num_sequences} seqs, temp={sampling_temp}, "
            f"redesigned={redesigned_residues or 'all'}"
        )

        env = {**os.environ, "PYTHONPATH": str(_SRC_DIR)}
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if proc.returncode != 0:
            raise RuntimeError(
                f"LigandMPNN exited {proc.returncode}:\n{proc.stderr[-1000:]}"
            )

        seqs_dir = out_dir / "seqs"
        if not seqs_dir.exists():
            raise RuntimeError(
                f"No seqs/ output dir. Stderr: {proc.stderr[-500:]}"
            )

        sequences, scores = _parse_fasta_dir(seqs_dir)
        _progress(f"LigandMPNN done: {len(sequences)} sequences.")
        return {"sequences": sequences, "scores": scores}


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
