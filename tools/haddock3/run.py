#!/usr/bin/env python
"""HADDOCK3 tool runner. Reads JSON inputs from stdin, writes JSON outputs to stdout.
Runs inside tools/haddock3/.venv — do NOT run with backend venv python.
"""
import csv
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Ensure pdb_tools and haddock3 binaries (installed in this venv) are on PATH
_VENV_BIN = str(Path(sys.executable).parent)
_ENV = {**os.environ, "PATH": f"{_VENV_BIN}:{os.environ.get('PATH', '')}"}

_ARTIFACT_DIR = Path(os.getenv("PDP_RUN_LOG_DIR", "/tmp/pdp-runs"))
_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def _save_artifacts(run_dir: str, best_complex: str | None, scores: dict) -> str:
    """Copy docking results to a persistent directory so they survive tempdir cleanup."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = _ARTIFACT_DIR / f"haddock3_{stamp}"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "scores.json").write_text(json.dumps(scores, indent=2))
    if best_complex:
        (dest / "best_complex.pdb").write_text(best_complex)
    # Copy full caprieval dir for debugging
    for caprieval_dir in sorted(glob.glob(os.path.join(run_dir, "*_caprieval")))[-1:]:
        try:
            shutil.copytree(caprieval_dir, dest / "caprieval", dirs_exist_ok=True)
        except Exception:
            pass
    _progress(f"Artifacts saved to {dest}")
    return str(dest)


def _run(cmd: str, cwd: str, label: str = "") -> None:
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, env=_ENV)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()[-1000:]
        raise RuntimeError(f"{label or cmd} failed (exit {r.returncode}): {err}")


def _run_streaming(cmd: str, cwd: str, label: str = "") -> None:
    """Like _run but forwards each output line to stderr in real time."""
    proc = subprocess.Popen(
        cmd, shell=True, cwd=cwd, env=_ENV,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    lines: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            lines.append(line)
            print(line, file=sys.stderr, flush=True)
    proc.wait()
    if proc.returncode != 0:
        err = "\n".join(lines[-20:])
        raise RuntimeError(f"{label or cmd} failed (exit {proc.returncode}): {err}")


def _write_act_pass(path: str, active: str, passive: str = "") -> None:
    with open(path, "w") as f:
        f.write(active.strip() + "\n")
        f.write(passive.strip() + "\n")


def _extract_vh_sequence(pdb_path: str) -> str:
    """Extract amino acid sequence from a single-chain PDB using pdb_tofasta."""
    r = subprocess.run(
        f"pdb_tofasta {os.path.basename(pdb_path)}",
        shell=True, capture_output=True, text=True, env=_ENV,
        cwd=os.path.dirname(pdb_path),
    )
    seq = ""
    for line in r.stdout.splitlines():
        if not line.startswith(">"):
            seq += line.strip()
    return seq


def _detect_cdrs_chothia(pdb_path: str) -> tuple[list[int], list[int], list[int]] | None:
    """
    Use abnumber/ANARCI to detect CDR-H1/2/3 as 1-based sequential residue numbers
    matching the sequential numbering produced by pdb_reres -1 on the same PDB.
    Returns (cdr1, cdr2, cdr3) lists or None on failure.
    """
    try:
        from abnumber import Chain  # requires anarci in the same venv
        seq = _extract_vh_sequence(pdb_path)
        if len(seq) < 50:
            return None
        chain = Chain(seq, scheme="chothia")
        all_pos = list(chain.positions.keys())
        pos_to_seq = {p: i + 1 for i, p in enumerate(all_pos)}
        cdr1 = sorted(pos_to_seq[p] for p in chain.cdr1_dict if p in pos_to_seq)
        cdr2 = sorted(pos_to_seq[p] for p in chain.cdr2_dict if p in pos_to_seq)
        cdr3 = sorted(pos_to_seq[p] for p in chain.cdr3_dict if p in pos_to_seq)
        if not (cdr1 and cdr2 and cdr3):
            return None
        _progress(
            f"ANARCI CDR detection (Chothia): "
            f"H1={cdr1[0]}-{cdr1[-1]}, H2={cdr2[0]}-{cdr2[-1]}, H3={cdr3[0]}-{cdr3[-1]}"
        )
        return cdr1, cdr2, cdr3
    except Exception as exc:
        _progress(f"WARN: CDR auto-detection failed ({exc}); falling back to provided positions")
        return None


def _write_config(path: str, run_dir: str, sampling: int, select_top: int) -> None:
    with open(path, "w") as f:
        f.write(f"""
run_dir = "{run_dir}"
mode = "local"
ncores = 4
self_contained = true
postprocess = true
clean = true

molecules = [
    "antibody_clean.pdb",
    "antigen_clean.pdb"
]

[topoaa]

[rigidbody]
ambig_fname = "ambig-restraints.tbl"
unambig_fname = "antibody-unambig.tbl"
sampling = {sampling}

[caprieval]

[seletop]
select = {select_top}

[flexref]
tolerance = 5
ambig_fname = "ambig-restraints.tbl"
unambig_fname = "antibody-unambig.tbl"

[caprieval]

[emref]
tolerance = 5
ambig_fname = "ambig-restraints.tbl"
unambig_fname = "antibody-unambig.tbl"

[caprieval]

[clustfcc]
plot_matrix = true

[seletopclusts]
top_models = 4

[caprieval]

[contactmap]
""")


def _parse_capri(tsv_path: str) -> dict:
    metrics = ["score", "vdw", "desolv", "air", "bsa"]
    clusters: dict[int, list] = {}
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                cr = int(float(row.get("cluster_ranking", 0) or 0))
            except (ValueError, TypeError):
                continue
            clusters.setdefault(cr, []).append(row)
    if not clusters:
        return {}
    top = clusters[min(clusters)]
    result: dict = {"n_models": len(top)}
    for m in metrics:
        vals = []
        for row in top:
            try:
                vals.append(float(row[m]))
            except Exception:
                pass
        if vals:
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
            result[m] = round(mean, 3)
            result[f"{m}_std"] = round(std, 3)
    return result


def _best_complex(tsv_path: str) -> str | None:
    best_path, best_rank = None, float("inf")
    with open(tsv_path) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            try:
                rank = int(float(row.get("caprieval_rank", 9999)))
                if rank < best_rank:
                    best_rank = rank
                    rel = row.get("model", "")
                    best_path = os.path.normpath(
                        os.path.join(os.path.dirname(tsv_path), rel)
                    )
            except Exception:
                pass
    if best_path and os.path.exists(best_path):
        print(f"Best complex: {best_path} (rank {best_rank})", file=sys.stderr, flush=True)
        return open(best_path).read()
    # Path from TSV not found — search run directory broadly for any docked PDB
    run_dir = os.path.dirname(os.path.dirname(tsv_path))
    for pattern in [
        os.path.join(run_dir, "*_seletopclusts", "cluster_1_model_1.pdb"),
        os.path.join(run_dir, "*_seletopclusts", "*.pdb"),
        os.path.join(run_dir, "*_rigidbody", "rigidbody_1.pdb"),
        os.path.join(run_dir, "**", "*.pdb"),
    ]:
        pdbs = sorted(glob.glob(pattern, recursive=True))
        if pdbs:
            print(f"Fallback best complex: {pdbs[0]}", file=sys.stderr, flush=True)
            return open(pdbs[0]).read()
    print("WARNING: no docked PDB found anywhere in run dir", file=sys.stderr, flush=True)
    return None


def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _first_protein_chain(pdb_text: str) -> str:
    """Return the first chain ID that has ATOM records (protein/nucleic)."""
    for line in pdb_text.splitlines():
        if line.startswith("ATOM"):
            return line[21]
    return "A"


def main() -> None:
    inputs = json.load(sys.stdin)

    antibody_pdb       = str(inputs["antibody"])
    antigen_pdb        = str(inputs["antigen"])
    antigen_chains     = str(inputs.get("antigen_chains", "")).strip().upper()
    antigen_active     = str(inputs.get("antigen_active_residues", "")).strip()
    antigen_passive    = str(inputs.get("antigen_passive_residues", "")).strip()
    cdr1 = (int(inputs.get("cdr1_start", 26)), int(inputs.get("cdr1_end", 35)))
    cdr2 = (int(inputs.get("cdr2_start", 50)), int(inputs.get("cdr2_end", 58)))
    cdr3 = (int(inputs.get("cdr3_start", 95)), int(inputs.get("cdr3_end", 102)))
    vh    = str(inputs.get("vh_chain", "H")).upper()
    vl    = str(inputs.get("vl_chain", "L") or "").upper()
    sampling   = max(1, int(inputs.get("rigid_sampling", 100)))
    select_top = max(1, int(inputs.get("select_top", 50)))
    nanobody   = not bool(vl)

    _debug_dir = os.getenv("HADDOCK3_KEEP_WORKDIR")
    _tmpobj = None if _debug_dir else tempfile.TemporaryDirectory()
    d = _debug_dir if _debug_dir else _tmpobj.name
    _failed = False
    try:
        _progress("Writing input PDBs…")
        open(os.path.join(d, "antibody_raw.pdb"), "w").write(antibody_pdb)
        open(os.path.join(d, "antigen_raw.pdb"),  "w").write(antigen_pdb)

        _progress(f"Cleaning antibody ({'nanobody' if nanobody else 'VH+VL'})…")
        if nanobody:
            # For nanobody: extract VH-only, keep intermediate before renumbering for CDR detection
            _run(
                f"pdb_tidy -strict antibody_raw.pdb | pdb_selchain -{vh} "
                "| pdb_delhetatm | pdb_delelem -H | pdb_fixinsert | pdb_selaltloc | pdb_keepcoord"
                "| pdb_tidy -strict > antibody_vh_raw.pdb",
                cwd=d, label="extract_nb"
            )
            _run(
                "pdb_reres -1 antibody_vh_raw.pdb | pdb_chain -A | pdb_chainxseg | pdb_tidy -strict "
                "> antibody_clean.pdb",
                cwd=d, label="clean_antibody"
            )
            _vh_for_cdr = os.path.join(d, "antibody_vh_raw.pdb")
        else:
            _run(
                f"pdb_tidy -strict antibody_raw.pdb | pdb_selchain -{vh} "
                "| pdb_delhetatm | pdb_delelem -H | pdb_fixinsert | pdb_selaltloc | pdb_keepcoord"
                "| pdb_tidy -strict > antibody_H.pdb",
                cwd=d, label="extract VH"
            )
            _run(
                f"pdb_tidy -strict antibody_raw.pdb | pdb_selchain -{vl} "
                "| pdb_delhetatm | pdb_delelem -H | pdb_fixinsert | pdb_selaltloc | pdb_keepcoord"
                "| pdb_tidy -strict > antibody_L.pdb",
                cwd=d, label="extract VL"
            )
            _run(
                "pdb_merge antibody_H.pdb antibody_L.pdb "
                "| pdb_reres -1 | pdb_chain -A | pdb_chainxseg | pdb_tidy -strict "
                "> antibody_clean.pdb",
                cwd=d, label="merge antibody"
            )
            # CDR detection on VH before merging; positions stay valid because VH is always first
            _vh_for_cdr = os.path.join(d, "antibody_H.pdb")

        _progress("Cleaning antigen (preserving original residue numbers)…")
        # Parse comma-separated chain list; auto-detect first protein chain if not set
        _raw_chains = [c.strip() for c in antigen_chains.split(",") if c.strip()]
        if not _raw_chains:
            _raw_chains = [_first_protein_chain(antigen_pdb)]
        _sel = ",".join(_raw_chains)
        _antigen_segid = _raw_chains[0]  # segid used in restraints (epitope must be on first chain)
        _progress(f"Antigen: chains={_sel!r}, restraint segid={_antigen_segid!r} "
                  f"(set antigen_chains param to override, e.g. 'A' or 'A,C')")
        if len(_raw_chains) == 1:
            # Single chain: rename to B (HADDOCK3 two-body convention)
            _run(
                f"pdb_tidy -strict antigen_raw.pdb | pdb_selchain -{_sel} "
                "| pdb_delhetatm | pdb_delelem -H | pdb_fixinsert "
                "| pdb_selaltloc | pdb_keepcoord "
                "| pdb_chain -B | pdb_chainxseg | pdb_tidy -strict "
                "> antigen_clean.pdb",
                cwd=d, label="clean_antigen"
            )
            _antigen_segid = "B"
        else:
            # Multi-chain: keep original chain IDs, propagate as segIDs
            _run(
                f"pdb_tidy -strict antigen_raw.pdb | pdb_selchain -{_sel} "
                "| pdb_delhetatm | pdb_delelem -H | pdb_fixinsert "
                "| pdb_selaltloc | pdb_keepcoord "
                "| pdb_chainxseg | pdb_tidy -strict "
                "> antigen_clean.pdb",
                cwd=d, label="clean_antigen"
            )

        _progress("Detecting CDR residues via ANARCI (Chothia scheme)…")
        _detected = _detect_cdrs_chothia(_vh_for_cdr)
        if _detected:
            active_cdr = _detected[0] + _detected[1] + _detected[2]
        else:
            # Fall back to user-provided / default positions
            active_cdr = (
                list(range(cdr1[0], cdr1[1] + 1))
                + list(range(cdr2[0], cdr2[1] + 1))
                + list(range(cdr3[0], cdr3[1] + 1))
            )
            _progress(f"Using fallback CDR positions: H1={cdr1}, H2={cdr2}, H3={cdr3}")
        _write_act_pass(os.path.join(d, "antibody-cdr.act-pass"),
                        " ".join(map(str, active_cdr)))
        _write_act_pass(os.path.join(d, "antigen-rbm.act-pass"), antigen_active, antigen_passive)

        _progress("Generating ambiguous restraints (CDR ↔ epitope)…")
        _run(
            "haddock3-restraints active_passive_to_ambig "
            "antibody-cdr.act-pass antigen-rbm.act-pass "
            f"--segid-one A --segid-two {_antigen_segid} > ambig-restraints.tbl",
            cwd=d, label="ambig_restraints"
        )
        _run("haddock3-restraints validate_tbl ambig-restraints.tbl --silent",
             cwd=d, label="validate ambig")

        if not nanobody:
            _progress("Generating unambiguous body restraints…")
            _run("haddock3-restraints restrain_bodies antibody_clean.pdb "
                 "> antibody-unambig.tbl",
                 cwd=d, label="unambig_restraints")
            _run("haddock3-restraints validate_tbl antibody-unambig.tbl --silent",
                 cwd=d, label="validate unambig")
        else:
            open(os.path.join(d, "antibody-unambig.tbl"), "w").close()

        _progress(f"Launching HADDOCK3 docking (sampling={sampling}, select_top={select_top})…")
        cfg_path = os.path.join(d, "docking.cfg")
        _write_config(cfg_path, os.path.join(d, "run"), sampling, select_top)
        _run_streaming(f"haddock3 {cfg_path}", cwd=d, label="haddock3")
        _progress("HADDOCK3 docking complete — parsing CAPRI scores…")

        # Find the last caprieval directory — step number depends on config module count
        caprieval_dirs = sorted(glob.glob(os.path.join(d, "run", "*_caprieval")))
        if not caprieval_dirs:
            raise RuntimeError("HADDOCK3 finished but no caprieval directory found in run/")
        capri_tsv = os.path.join(caprieval_dirs[-1], "capri_ss.tsv")
        _progress(f"Reading scores from {os.path.basename(caprieval_dirs[-1])}/capri_ss.tsv")
        if not os.path.exists(capri_tsv):
            raise RuntimeError(f"HADDOCK3 finished but capri_ss.tsv not found in {caprieval_dirs[-1]}")

        scores = _parse_capri(capri_tsv)
        best_complex = _best_complex(capri_tsv)
        artifact_dir = _save_artifacts(os.path.join(d, "run"), best_complex, scores)

    except Exception:
        _failed = True
        raise
    finally:
        if _tmpobj is not None:
            if _failed:
                # Keep work dir for debugging; copy it out before TemporaryDirectory cleanup
                debug_dest = _ARTIFACT_DIR / f"haddock3_failed_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
                try:
                    shutil.copytree(_tmpobj.name, str(debug_dest))
                    _progress(f"Work dir preserved at {debug_dest} for debugging")
                except Exception:
                    pass
            _tmpobj.cleanup()

    json.dump({"best_complex": best_complex, "scores": scores, "artifact_dir": artifact_dir}, sys.stdout)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)
