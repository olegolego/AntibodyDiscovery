#!/usr/bin/env python3
"""MEGADOCK subprocess entry point. Reads JSON from stdin, writes JSON to stdout.

Inputs:
  receptor          : str  — PDB text
  ligand            : str  — PDB text
  num_predictions   : int  — top poses to return (default 5)
  rotational_sampling: int — 3600 or 54000 (default 3600)
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

_HERE          = Path(__file__).resolve().parent
_BIN           = _HERE / "bin"
_MEGADOCK      = _BIN / "megadock"
_MEGADOCK_METAL = _BIN / "megadock-metal"
_DECOYGEN      = _BIN / "decoygen"


def _pick_megadock_binary() -> Path:
    """Return megadock-metal on Apple Silicon when available, else megadock."""
    import platform
    if platform.machine() == "arm64" and _MEGADOCK_METAL.exists():
        return _MEGADOCK_METAL
    return _MEGADOCK

_MAX_RECEPTOR_RESIDUES = 600


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _trim_to_best_chain(pdb_text: str, max_res: int = _MAX_RECEPTOR_RESIDUES) -> str:
    """Select the single chain with most residues ≤ max_res from a large PDB."""
    from collections import defaultdict
    chains: dict[str, list[str]] = defaultdict(list)
    res_per_chain: dict[str, set] = defaultdict(set)
    for line in pdb_text.splitlines():
        if line.startswith("ATOM"):
            ch = line[21] if len(line) > 21 else " "
            try:
                rn = int(line[22:26])
            except ValueError:
                rn = 0
            chains[ch].append(line)
            res_per_chain[ch].add(rn)
    total = sum(len(v) for v in res_per_chain.values())
    if total <= max_res:
        return pdb_text
    _progress(
        f"⚠ Receptor has ~{total} residues — MEGADOCK limited to {max_res}. "
        "Auto-selecting best chain."
    )
    chosen = None
    for ch, res in sorted(res_per_chain.items(), key=lambda x: -len(x[1])):
        if len(res) <= max_res:
            chosen = ch
            break
    if chosen is None:
        chosen = min(res_per_chain, key=lambda c: len(res_per_chain[c]))
    _progress(
        f"→ Using chain {chosen!r} "
        f"({len(res_per_chain[chosen])} residues, "
        f"dropped {total - len(res_per_chain[chosen])} residues)"
    )
    return "\n".join(chains[chosen]) + "\nEND\n"


def _parse_scores(out_file: Path) -> list[dict]:
    """Parse MEGADOCK .out file — returns [{rank, score}] best-first."""
    scores = []
    with open(out_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            # docking result lines: angle1 angle2 angle3 tx ty tz score (7 fields)
            # header / center lines have 2-4 fields — skip them
            if len(parts) < 7:
                continue
            try:
                score = float(parts[-1])
                scores.append(score)
            except ValueError:
                continue
    return [{"rank": i + 1, "score": s} for i, s in enumerate(scores)]


def _render_docking_image(complex_pdb: str, rank: int = 1) -> str:
    """2-D Cα scatter of docked complex, chains colored individually. Returns data-URL or ''."""
    import base64, io
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return ""

    chains: dict[str, list] = {}
    for line in complex_pdb.splitlines():
        if line.startswith("ATOM") and line[13:16].strip() == "CA":
            ch = line[21] if len(line) > 21 else "?"
            try:
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
                chains.setdefault(ch, []).append((x, y, z))
            except ValueError:
                pass
    if not chains:
        return ""

    COLORS = ["#fb923c", "#60a5fa", "#a78bfa", "#34d399", "#f472b6", "#fbbf24"]
    fig, ax = plt.subplots(figsize=(4, 4), facecolor="#0d1117")
    ax.set_facecolor("#0d1117")
    for i, (ch, coords) in enumerate(chains.items()):
        arr = np.array(coords)
        ax.scatter(arr[:, 0], arr[:, 1], s=8, alpha=0.75,
                   color=COLORS[i % len(COLORS)], label=f"Chain {ch}", linewidths=0)
    ax.legend(fontsize=7, facecolor="#1e2535", edgecolor="#374151",
              labelcolor="white", framealpha=0.9)
    ax.set_xlabel("X (Å)", fontsize=7, color="#64748b")
    ax.set_ylabel("Y (Å)", fontsize=7, color="#64748b")
    ax.tick_params(colors="#64748b", labelsize=6)
    for spine in ax.spines.values():
        spine.set_color("#1e2535")
    ax.set_title(f"MEGADOCK · rank {rank} pose · Cα projection", fontsize=7,
                 color="#cbd5e1", pad=5)
    plt.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode()


def _run(inputs: dict) -> dict:
    receptor_pdb = (inputs.get("receptor") or "").strip()
    ligand_pdb   = (inputs.get("ligand")   or "").strip()
    num_pred     = max(1, min(20, int(inputs.get("num_predictions", 5))))
    rot_sampling = int(inputs.get("rotational_sampling", 3600))
    if rot_sampling not in (3600, 54000):
        _progress(f"⚠ rotational_sampling={rot_sampling} is invalid — must be 3600 or 54000, using 3600")
        rot_sampling = 3600

    if not receptor_pdb:
        raise ValueError("receptor PDB is required")
    if not ligand_pdb:
        raise ValueError("ligand PDB is required")

    megadock_bin = _pick_megadock_binary()
    if not megadock_bin.exists():
        raise FileNotFoundError(
            f"MEGADOCK binary not found at {megadock_bin}.\n"
            f"Run: bash {_HERE}/setup.sh  (CPU)  or\n"
            f"     bash {_HERE}/setup_apple_silicon.sh  (Metal GPU, Apple Silicon)"
        )
    if megadock_bin == _MEGADOCK_METAL:
        _progress("Using megadock-metal (Apple Silicon GPU)")

    # Trim large receptors to avoid memory/time explosion
    receptor_pdb = _trim_to_best_chain(receptor_pdb)

    with tempfile.TemporaryDirectory(prefix="mgd_") as tmpdir:
        tmpdir = Path(tmpdir)
        rec_path = tmpdir / "receptor.pdb"
        lig_path = tmpdir / "ligand.pdb"
        out_path = tmpdir / "output.out"
        rec_path.write_text(receptor_pdb)
        lig_path.write_text(ligand_pdb)

        cmd = [
            str(megadock_bin),
            "-R", str(rec_path),
            "-L", str(lig_path),
            "-o", str(out_path),
            "-N", str(num_pred),
        ]
        # Fine rotational sampling: -D flag = 54000 rotations
        if rot_sampling == 54000:
            cmd.append("-D")

        # Metal binary: use all physical CPU cores for maximum throughput.
        # Each OMP thread handles one rotation via Metal GPU + CPU FFT.
        env = os.environ.copy()
        if megadock_bin == _MEGADOCK_METAL:
            import multiprocessing
            ncpu = str(multiprocessing.cpu_count())
            env.setdefault("OMP_NUM_THREADS", ncpu)

        _progress(
            f"MEGADOCK docking | {rot_sampling} rotations | top {num_pred} predictions"
        )
        t0 = time.time()

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(tmpdir),
            env=env,
        )

        stop_heartbeat = threading.Event()

        def _heartbeat() -> None:
            t0 = time.time()
            while not stop_heartbeat.wait(timeout=10):
                _progress(f"⏳ Docking in progress... ({time.time() - t0:.0f}s elapsed)")

        hb = threading.Thread(target=_heartbeat, daemon=True)
        hb.start()
        try:
            for raw in proc.stdout:  # type: ignore[union-attr]
                line = raw.rstrip()
                # MEGADOCK prints one line per hydrogen atom — suppress to avoid log flood
                if line and "contains hydrogen atom" not in line:
                    _progress(line)
            proc.wait()
        finally:
            stop_heartbeat.set()
            hb.join()

        if proc.returncode != 0:
            raise RuntimeError(f"MEGADOCK exited with code {proc.returncode}")
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RuntimeError("MEGADOCK produced no output file")

        elapsed = round(time.time() - t0, 1)
        _progress(f"Docking complete in {elapsed}s — generating top {num_pred} complexes")

        scores = _parse_scores(out_path)[:num_pred]

        # Generate docked complexes via decoygen
        receptor_atom_lines = "\n".join(
            l for l in receptor_pdb.splitlines()
            if l.startswith("ATOM") or l.startswith("HETATM")
        )

        top_results: list[dict] = []
        for entry in scores:
            rank = entry["rank"]
            out_lig = tmpdir / f"docked_lig_{rank}.pdb"
            degen_cmd = [
                str(_DECOYGEN),
                str(out_lig),
                str(lig_path),
                str(out_path),
                str(rank),
            ]
            r = subprocess.run(degen_cmd, capture_output=True, text=True, cwd=str(tmpdir))
            if r.returncode != 0 or not out_lig.exists():
                _progress(f"⚠ decoygen failed for rank {rank}: {r.stderr[:200]}")
                continue
            docked_lig_text = out_lig.read_text()
            complex_pdb = (
                f"MODEL {rank}\n"
                + docked_lig_text.rstrip()
                + "\n"
                + receptor_atom_lines
                + "\nENDMDL\n"
            )
            top_results.append({
                "rank":        rank,
                "score":       entry["score"],
                "complex_pdb": complex_pdb,
            })
            _progress(f"  rank {rank}: score={entry['score']:.3f}")

        if not top_results:
            raise RuntimeError("decoygen failed to produce any docked complexes")

        best = top_results[0]
        _progress(f"Done — best score: {best['score']:.3f}")

        _progress("Rendering docking visualization…")
        image = _render_docking_image(best["complex_pdb"], rank=1)

        outputs: dict = {
            "top_scores": [{"rank": r["rank"], "score": r["score"]} for r in top_results],
            "metadata": {
                "num_predictions":    num_pred,
                "rotational_sampling": rot_sampling,
                "elapsed_seconds":    elapsed,
                "best_score":         best["score"],
            },
            "image": image,
        }
        for r in top_results:
            outputs[f"complex_{r['rank']}"] = r["complex_pdb"]
        return outputs


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
