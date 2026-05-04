#!/usr/bin/env python3
"""GROMACS MD + MM/GBSA subprocess entry point.

Reads JSON from stdin, writes JSON to stdout.
Every stderr line is forwarded live to the UI terminal.

Pipeline:
  pdb2gmx → editconf → solvate → genion → EM → NVT → NPT → mdrun →
  trjconv (PBC fix + fit) → index creation → gmx_MMPBSA → parse results
"""
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple

# ── Progress ───────────────────────────────────────────────────────────────────

def _progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ── GROMACS binary detection ───────────────────────────────────────────────────

_CONDA_MMPBSA = os.path.expanduser("~/miniforge3/envs/mmpbsa/bin")


def _find_bin(name: str) -> str:
    """Return the path of a binary, checking the conda mmpbsa env first."""
    candidates = [
        str(Path(_CONDA_MMPBSA) / name),
        os.path.expanduser(f"~/miniforge3/envs/mmpbsa/bin/{name}"),
        os.path.expanduser(f"~/mambaforge/envs/mmpbsa/bin/{name}"),
        os.path.expanduser(f"~/miniconda3/envs/mmpbsa/bin/{name}"),
        os.path.expanduser(f"~/anaconda3/envs/mmpbsa/bin/{name}"),
        # AVX2 GROMACS build
        os.path.expanduser(f"~/miniforge3/envs/mmpbsa/bin.AVX2_256/{name}"),
        shutil.which(name) or "",
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return name


def _find_gmx() -> str:
    return _find_bin("gmx")


def _n_threads() -> int:
    return max(1, os.cpu_count() or 1)


# ── Subprocess wrapper ─────────────────────────────────────────────────────────

def _run(
    cmd,
    cwd: Path,
    stdin_text: Optional[str] = None,
    check: bool = True,
    label: str = "",
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Prepend conda mmpbsa bin so gmx_MMPBSA can find cpptraj and other deps
    mmpbsa_bin = str(Path(_CONDA_MMPBSA))
    env["PATH"] = mmpbsa_bin + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd),
        input=stdin_text,
        text=True,
        capture_output=True,
        env=env,
    )
    if check and result.returncode != 0:
        tag = label or " ".join(str(c) for c in cmd[:3])
        detail = (result.stderr or result.stdout or "")[-1000:]
        raise RuntimeError(f"{tag} failed (exit {result.returncode}): {detail}")
    return result


# ── Index file creation (replaces rips_build_ndx.py) ──────────────────────────

def _create_chain_index(
    ref_pdb: Path,
    ndx_path: Path,
    receptor_chains: str,
    ligand_chains: str,
) -> None:
    """Parse ref PDB and write GROMACS ndx with Receptor and Ligand groups.

    Protein atoms are first in a GROMACS topology (pdb2gmx puts protein before
    solvent/ions), so 1-based atom numbers in the protein-only reference PDB
    map directly to global atom numbers in the full system.
    """
    rec_set = {c.strip().upper() for c in receptor_chains.split(",") if c.strip()}
    lig_set = {c.strip().upper() for c in ligand_chains.split(",") if c.strip()}

    rec_atoms: list[int] = []
    lig_atoms: list[int] = []

    with open(ref_pdb) as f:
        for line in f:
            if not (line.startswith("ATOM") or line.startswith("HETATM")):
                continue
            chain = line[21].strip().upper()
            try:
                idx = int(line[6:11])
            except ValueError:
                continue
            if chain in rec_set:
                rec_atoms.append(idx)
            elif chain in lig_set:
                lig_atoms.append(idx)

    if not rec_atoms:
        raise ValueError(
            f"No atoms found for receptor chains {rec_set} in {ref_pdb}. "
            f"Available chains: check the reference PDB."
        )
    if not lig_atoms:
        raise ValueError(
            f"No atoms found for ligand chains {lig_set} in {ref_pdb}. "
            f"Available chains: check the reference PDB."
        )

    def _write_group(fh, name: str, atoms: list[int]) -> None:
        fh.write(f"[ {name} ]\n")
        for i, a in enumerate(atoms):
            fh.write(f" {a:5d}")
            if (i + 1) % 15 == 0:
                fh.write("\n")
        fh.write("\n\n")

    with open(ndx_path, "w") as fh:
        _write_group(fh, "Receptor", rec_atoms)
        _write_group(fh, "Ligand", lig_atoms)

    _progress(
        f"  Index: Receptor={len(rec_atoms)} atoms (chains {sorted(rec_set)}), "
        f"Ligand={len(lig_atoms)} atoms (chains {sorted(lig_set)})"
    )


# ── gmx check helpers ──────────────────────────────────────────────────────────

def _parse_gmx_check(stderr: str) -> Dict[str, Optional[float]]:
    lines = []
    for line in stderr.split("\n"):
        lines.append(line.split("\r")[-1] if "\r" in line else line)
    text = "\n".join(lines)

    m_last = re.search(r"Last frame\s+(\d+)(?:\s+time\s+([0-9.eE+-]+))?", text)
    last_frame = int(m_last.group(1)) if m_last else 0
    last_time = float(m_last.group(2)) if (m_last and m_last.group(2)) else None

    m_first = re.search(r"First frame\s+(\d+)(?:\s+time\s+([0-9.eE+-]+))?", text)
    first_frame = int(m_first.group(1)) if m_first else 0
    first_time = float(m_first.group(2)) if (m_first and m_first.group(2)) else 0.0

    return {
        "first_frame": first_frame,
        "first_time_ps": first_time or 0.0,
        "last_frame": last_frame,
        "last_time_ps": last_time,
    }


def _estimate_dt_ps(
    first_frame: int, last_frame: int, first_time: float, last_time: Optional[float]
) -> Optional[float]:
    if last_time is None:
        return None
    span = last_frame - first_frame
    return (last_time - first_time) / span if span > 0 else None


def _ndx_group_order(ndx_path: Path) -> Dict[str, int]:
    text = ndx_path.read_text(encoding="utf-8", errors="replace")
    names = re.findall(r"^\s*\[\s*(.*?)\s*\]\s*$", text, flags=re.MULTILINE)
    if not names:
        raise ValueError(f"No groups found in {ndx_path}")
    return {name: idx for idx, name in enumerate(names)}


def _time_to_frame_1based(
    target_ps: float, first_ps: float, dt_ps: float, total: int
) -> int:
    if dt_ps <= 0:
        return 1
    f = int(math.floor((target_ps - first_ps) / dt_ps)) + 1
    return max(1, min(total, f))


# ── Regenerate reference PDB (Receptor+Ligand only) ────────────────────────────

def _regenerate_reference_pdb(
    work_dir: Path, job_name: str, gmx: str
) -> None:
    """Re-extract reference PDB from trajectory using only Receptor+Ligand atoms."""
    ndx_path = work_dir / f"{job_name}_index.ndx"
    ref_pdb = work_dir / f"{job_name}_md_ref.pdb"
    backup = work_dir / f"{job_name}_md_ref_full.pdb"

    if ref_pdb.exists() and not backup.exists():
        shutil.copy(ref_pdb, backup)

    text = ndx_path.read_text(encoding="utf-8", errors="replace")
    rec_atoms: list[int] = []
    lig_atoms: list[int] = []
    current = None
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("["):
            current = s.strip("[] ")
        elif s and current:
            atoms = [int(x) for x in s.split() if x.isdigit()]
            if current == "Receptor":
                rec_atoms.extend(atoms)
            elif current == "Ligand":
                lig_atoms.extend(atoms)

    combined = sorted(rec_atoms + lig_atoms)
    tmp_ndx = work_dir / f"{job_name}_combined.ndx"
    with open(tmp_ndx, "w") as fh:
        fh.write("[ Complex ]\n")
        for i, a in enumerate(combined):
            fh.write(f" {a:5d}")
            if (i + 1) % 15 == 0:
                fh.write("\n")
        fh.write("\n")

    _run(
        [gmx, "trjconv",
         "-s", f"{job_name}_md.tpr",
         "-f", f"{job_name}_md.gro",
         "-n", tmp_ndx.name,
         "-o", ref_pdb.name],
        cwd=work_dir,
        stdin_text="Complex\n",
        label="trjconv:regenerate_ref",
    )
    tmp_ndx.unlink(missing_ok=True)
    _progress(f"  Reference PDB regenerated: {len(combined)} Receptor+Ligand atoms")


# ── Complex pre-processing ────────────────────────────────────────────────────

def _prepare_complex_pdb(pdb_text: str) -> str:
    """Strip MODEL/ENDMDL and translate chains displaced by MEGADOCK grid positioning.

    MEGADOCK places the docked structure at an arbitrary FFT grid offset — often
    20-40 nm from the receptor — causing a multi-GB solvation box and a fatal
    'excluded atoms > cutoff' NVT error.

    Two-pass approach:
      Pass 1: collect Cα centroids per chain, build per-chain translation vectors.
      Pass 2: re-stream the ORIGINAL lines in order (preserving TER/END between
              chains so pdb2gmx never sees a phantom cross-chain peptide bond),
              applying coordinate translations in-place.
    """
    import math

    # ── Pass 1: centroids ────────────────────────────────────────────────────────
    chain_ca: dict[str, list] = {}
    has_atoms = False

    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        has_atoms = True
        ch = line[21] if len(line) > 21 else " "
        if line[13:16].strip() == "CA":
            try:
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
                chain_ca.setdefault(ch, []).append([x, y, z])
            except ValueError:
                pass

    if not has_atoms or not chain_ca:
        return pdb_text

    def centroid(pts: list) -> list:
        n = len(pts)
        return [sum(p[i] for p in pts) / n for i in range(3)]

    def dist(a: list, b: list) -> float:
        return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))

    # Reference = chain with the most Cα atoms (usually the target protein)
    ref_chain = max(chain_ca, key=lambda c: len(chain_ca[c]))
    ref_cen   = centroid(chain_ca[ref_chain])

    translations: dict[str, list] = {}
    for ch, pts in chain_ca.items():
        cen = centroid(pts)
        d   = dist(cen, ref_cen)
        if d > 50.0:  # > 50 Å → MEGADOCK grid displacement
            _progress(
                f"  ⚠ Chain {ch!r} centroid is {d:.1f} Å from receptor — "
                "translating to docking contact distance"
            )
            scale = 15.0 / d
            translations[ch] = [
                ref_cen[i] + (cen[i] - ref_cen[i]) * scale - cen[i]
                for i in range(3)
            ]
        else:
            translations[ch] = [0.0, 0.0, 0.0]

    # ── Pass 2: stream original lines in order, apply translations in-place ─────
    # Keeping TER/END/CONECT records at their original positions is critical —
    # moving them to the end would fuse separate chains into one polypeptide in
    # pdb2gmx, creating phantom cross-chain bonds spanning hundreds of Angstroms.
    result: list[str] = []
    for line in pdb_text.splitlines():
        if line.startswith(("MODEL", "ENDMDL")):
            continue  # strip multi-model markers
        if line.startswith(("ATOM", "HETATM")):
            ch = line[21] if len(line) > 21 else " "
            tx = translations.get(ch, [0.0, 0.0, 0.0])
            if any(abs(t) > 0.001 for t in tx):
                try:
                    x = float(line[30:38]) + tx[0]
                    y = float(line[38:46]) + tx[1]
                    z = float(line[46:54]) + tx[2]
                    line = f"{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}"
                except ValueError:
                    pass
        result.append(line)

    return "\n".join(result) + "\n"


# ── MD pipeline steps ──────────────────────────────────────────────────────────

def _generate_topology(
    work_dir: Path, job_name: str, input_pdb: Path,
    forcefield: str, water_model: str, gmx: str,
) -> None:
    _run(
        [gmx, "pdb2gmx",
         "-f", str(input_pdb),
         "-o", f"{job_name}_complex.gro",
         "-p", f"{job_name}_topol.top",
         "-i", f"{job_name}_posre.itp",
         "-ff", forcefield,
         "-water", water_model,
         "-merge", "no",
         "-ignh"],
        cwd=work_dir,
        label="pdb2gmx",
    )


def _create_box(work_dir: Path, job_name: str, gmx: str) -> None:
    _run(
        [gmx, "editconf",
         "-f", f"{job_name}_complex.gro",
         "-o", f"{job_name}_boxed.gro",
         "-c", "-d", "1.0", "-bt", "cubic"],
        cwd=work_dir,
        label="editconf",
    )


def _solvate(work_dir: Path, job_name: str, gmx: str) -> None:
    _run(
        [gmx, "solvate",
         "-cp", f"{job_name}_boxed.gro",
         "-cs", "spc216",
         "-o", f"{job_name}_solvated.gro",
         "-p", f"{job_name}_topol.top"],
        cwd=work_dir,
        label="solvate",
    )


def _add_ions(
    work_dir: Path, job_name: str, ion_conc: float, gmx: str,
) -> None:
    mdp = work_dir / f"{job_name}_ions.mdp"
    mdp.write_text(
        "integrator  = steep\nnsteps      = 500\nemtol       = 1000.0\n"
        "cutoff-scheme = Verlet\ncoulombtype = PME\n"
        "rcoulomb    = 1.0\nrvdw        = 1.0\npbc         = xyz\n"
    )
    _run(
        [gmx, "grompp",
         "-f", mdp.name,
         "-c", f"{job_name}_solvated.gro",
         "-p", f"{job_name}_topol.top",
         "-o", f"{job_name}_ions.tpr",
         "-maxwarn", "2"],
        cwd=work_dir,
        label="grompp:ions",
    )
    _run(
        [gmx, "genion",
         "-s", f"{job_name}_ions.tpr",
         "-o", f"{job_name}_ions.gro",
         "-p", f"{job_name}_topol.top",
         "-pname", "NA", "-nname", "CL",
         "-neutral", "-conc", str(ion_conc)],
        cwd=work_dir,
        stdin_text="SOL\n",
        label="genion",
    )


def _energy_minimization(
    work_dir: Path, job_name: str, gmx: str,
) -> None:
    out = work_dir / f"{job_name}_em.gro"
    if out.exists():
        _progress("  EM already done, skipping.")
        return

    nt = _n_threads()
    mdp = work_dir / f"{job_name}_em.mdp"
    mdp.write_text(
        "integrator  = steep\nnsteps      = 50000\nemtol       = 1000.0\n"
        "cutoff-scheme = Verlet\ncoulombtype = PME\n"
        "rcoulomb    = 1.0\nrvdw        = 1.0\npbc         = xyz\n"
        "constraints = h-bonds\n"
    )
    _run(
        [gmx, "grompp",
         "-f", mdp.name,
         "-c", f"{job_name}_ions.gro",
         "-p", f"{job_name}_topol.top",
         "-o", f"{job_name}_em.tpr",
         "-maxwarn", "2"],
        cwd=work_dir,
        label="grompp:em",
    )
    _run(
        [gmx, "mdrun",
         "-deffnm", f"{job_name}_em",
         "-ntmpi", "1", "-ntomp", str(nt)],
        cwd=work_dir,
        label="mdrun:em",
    )


def _run_nvt(
    work_dir: Path, job_name: str, temperature_k: float, nsteps: int, gmx: str,
) -> None:
    out = work_dir / f"{job_name}_nvt.gro"
    if out.exists():
        _progress("  NVT already done, skipping.")
        return

    nt = _n_threads()
    t = temperature_k
    mdp = work_dir / f"{job_name}_nvt.mdp"
    mdp.write_text(
        f"define = -DPOSRES\nintegrator  = md\ndt          = 0.002\n"
        f"nsteps      = {nsteps}\ncutoff-scheme = Verlet\n"
        f"nstxout-compressed = 10000\nnstenergy   = 5000\nnstlog      = 5000\n"
        f"coulombtype = PME\nrcoulomb    = 1.2\nrvdw        = 1.2\n"
        f"tcoupl      = V-rescale\ntc-grps     = Protein Non-Protein\n"
        f"tau_t       = 0.1 0.1\nref_t       = {t} {t}\n"
        f"pcoupl      = no\npbc         = xyz\ngen_vel     = yes\n"
        f"gen_temp    = {t}\nconstraints = h-bonds\n"
    )
    _run(
        [gmx, "grompp",
         "-f", mdp.name,
         "-c", f"{job_name}_em.gro",
         "-r", f"{job_name}_em.gro",
         "-p", f"{job_name}_topol.top",
         "-o", f"{job_name}_nvt.tpr",
         "-maxwarn", "2"],
        cwd=work_dir,
        label="grompp:nvt",
    )
    _run(
        [gmx, "mdrun",
         "-deffnm", f"{job_name}_nvt",
         "-ntmpi", "1", "-ntomp", str(nt)],
        cwd=work_dir,
        label="mdrun:nvt",
    )


def _run_npt(
    work_dir: Path, job_name: str, temperature_k: float, nsteps: int, gmx: str,
) -> None:
    out = work_dir / f"{job_name}_npt.gro"
    if out.exists():
        _progress("  NPT already done, skipping.")
        return

    nt = _n_threads()
    t = temperature_k
    mdp = work_dir / f"{job_name}_npt.mdp"
    mdp.write_text(
        f"define = -DPOSRES\nintegrator  = md\ndt          = 0.002\n"
        f"nsteps      = {nsteps}\ncutoff-scheme = Verlet\n"
        f"nstxout-compressed = 10000\nnstenergy   = 5000\nnstlog      = 5000\n"
        f"coulombtype = PME\nrcoulomb    = 1.2\nrvdw        = 1.2\n"
        f"tcoupl      = V-rescale\ntc-grps     = Protein Non-Protein\n"
        f"tau_t       = 0.1 0.1\nref_t       = {t} {t}\n"
        f"pcoupl      = C-rescale\npcoupltype  = Isotropic\n"
        f"tau_p       = 5.0\nref_p       = 1.0\ncompressibility = 4.5e-5\n"
        f"pbc         = xyz\ngen_vel     = no\ncontinuation = yes\n"
        f"constraints = h-bonds\n"
    )
    _run(
        [gmx, "grompp",
         "-f", mdp.name,
         "-c", f"{job_name}_nvt.gro",
         "-r", f"{job_name}_nvt.gro",
         "-t", f"{job_name}_nvt.cpt",
         "-p", f"{job_name}_topol.top",
         "-o", f"{job_name}_npt.tpr",
         "-maxwarn", "2"],
        cwd=work_dir,
        label="grompp:npt",
    )
    _run(
        [gmx, "mdrun",
         "-deffnm", f"{job_name}_npt",
         "-ntmpi", "1", "-ntomp", str(nt)],
        cwd=work_dir,
        label="mdrun:npt",
    )


def _run_production(
    work_dir: Path, job_name: str,
    temperature_k: float, production_ns: float, gmx: str,
) -> None:
    out = work_dir / f"{job_name}_md.gro"
    if out.exists():
        _progress("  Production MD already done, skipping.")
        return

    nt = _n_threads()
    t = temperature_k
    nsteps = int(production_ns * 500_000)   # 0.002 ps step → 500k steps/ns
    mdp = work_dir / f"{job_name}_md.mdp"
    # Use reaction-field instead of PME to avoid conda-forge GROMACS PME bug
    mdp.write_text(
        f"integrator  = md\ndt          = 0.002\nnsteps      = {nsteps}\n"
        f"cutoff-scheme = Verlet\nnstxout-compressed = 5000\n"
        f"nstenergy   = 5000\nnstlog      = 5000\n"
        f"coulombtype = reaction-field\nrcoulomb    = 1.0\nrvdw        = 1.0\n"
        f"epsilon_rf  = 0\n"
        f"tcoupl      = V-rescale\ntc-grps     = Protein Non-Protein\n"
        f"tau_t       = 0.1 0.1\nref_t       = {t} {t}\n"
        f"pcoupl      = Parrinello-Rahman\npcoupltype  = Isotropic\n"
        f"tau_p       = 2.0\nref_p       = 1.0\ncompressibility = 4.5e-5\n"
        f"pbc         = xyz\ngen_vel     = no\ncontinuation = yes\n"
        f"constraints = h-bonds\n"
    )
    _run(
        [gmx, "grompp",
         "-f", mdp.name,
         "-c", f"{job_name}_npt.gro",
         "-t", f"{job_name}_npt.cpt",
         "-p", f"{job_name}_topol.top",
         "-o", f"{job_name}_md.tpr",
         "-maxwarn", "2"],
        cwd=work_dir,
        label="grompp:md",
    )
    _run(
        [gmx, "mdrun",
         "-deffnm", f"{job_name}_md",
         "-nt", str(nt), "-ntmpi", "1"],
        cwd=work_dir,
        label="mdrun:production",
    )


def _prepare_trajectory(work_dir: Path, job_name: str, gmx: str) -> None:
    """Remove PBC, center, fit, and extract reference PDB."""
    _run(
        [gmx, "trjconv",
         "-s", f"{job_name}_md.tpr",
         "-f", f"{job_name}_md.xtc",
         "-o", f"{job_name}_md_centered.xtc",
         "-pbc", "mol", "-center"],
        cwd=work_dir,
        stdin_text="Protein\nSystem\n",
        label="trjconv:center",
    )
    _run(
        [gmx, "trjconv",
         "-s", f"{job_name}_md.tpr",
         "-f", f"{job_name}_md_centered.xtc",
         "-o", f"{job_name}_md_fit.xtc",
         "-fit", "rot+trans"],
        cwd=work_dir,
        stdin_text="Backbone\nSystem\n",
        label="trjconv:fit",
    )
    _run(
        [gmx, "trjconv",
         "-s", f"{job_name}_md.tpr",
         "-f", f"{job_name}_md.gro",
         "-o", f"{job_name}_md_ref.pdb"],
        cwd=work_dir,
        stdin_text="Protein\n",
        label="trjconv:ref_pdb",
    )
    centered = work_dir / f"{job_name}_md_centered.xtc"
    centered.unlink(missing_ok=True)


# ── MM/GBSA ────────────────────────────────────────────────────────────────────

def _run_mmpbsa(
    work_dir: Path,
    job_name: str,
    ion_concentration: float,
    discard_ns: float,
    production_ns: float,
    interval: int,
    igb: int,
    gmx: str,
) -> Dict:
    xtc = work_dir / f"{job_name}_md_fit.xtc"
    tpr = work_dir / f"{job_name}_md.tpr"
    top = work_dir / f"{job_name}_topol.top"
    ndx = work_dir / f"{job_name}_index.ndx"
    ref = work_dir / f"{job_name}_md_ref.pdb"

    for p in (xtc, tpr, top, ndx, ref):
        if not p.exists():
            raise FileNotFoundError(f"Required file not found: {p}")

    mmpbsa_bin = _find_bin("gmx_MMPBSA")
    if not Path(mmpbsa_bin).exists() and not shutil.which(mmpbsa_bin):
        raise RuntimeError(
            "gmx_MMPBSA not found. "
            "Install via: conda install -c conda-forge gmx_MMPBSA ambertools"
        )
    cpptraj_bin = _find_bin("cpptraj")
    if not Path(cpptraj_bin).exists() and not shutil.which(cpptraj_bin):
        raise RuntimeError(
            "cpptraj not found. "
            "Install via: conda install -c conda-forge ambertools"
        )

    # Detect trajectory frame count
    chk = _run([gmx, "check", "-f", xtc.name], cwd=work_dir, check=False)
    parsed = _parse_gmx_check(chk.stderr)
    last_0 = int(parsed["last_frame"])
    total = last_0 + 1
    first_ps = float(parsed["first_time_ps"] or 0.0)
    last_ps = parsed["last_time_ps"]
    dt_ps = _estimate_dt_ps(int(parsed["first_frame"]), last_0, first_ps, last_ps)

    if dt_ps and last_ps:
        discard_ps = max(0.0, discard_ns) * 1000.0
        start_ps = first_ps + discard_ps
        start_frame = _time_to_frame_1based(start_ps, first_ps, dt_ps, total)
    else:
        start_frame = min(201, total)

    end_frame = total
    start_frame = max(1, min(total, start_frame))
    end_frame = max(start_frame, end_frame)

    n_analyzed = 1 + (end_frame - start_frame) // interval
    _progress(
        f"  MM/GBSA: frames {start_frame}–{end_frame}, interval={interval} "
        f"→ {n_analyzed} frames analyzed"
    )

    group_map = _ndx_group_order(ndx)
    if "Receptor" not in group_map:
        raise KeyError(f"'Receptor' group not found in {ndx}. Groups: {list(group_map)}")
    if "Ligand" not in group_map:
        raise KeyError(f"'Ligand' group not found in {ndx}. Groups: {list(group_map)}")

    rec_gid = group_map["Receptor"]
    lig_gid = group_map["Ligand"]

    in_file = work_dir / f"{job_name}_mmpbsa.in"
    in_file.write_text(
        "&general\n"
        f"  startframe={start_frame}, endframe={end_frame}, interval={interval},\n"
        "  verbose=1,\n"
        "/\n"
        "&gb\n"
        f"  igb={igb}, saltcon={ion_concentration},\n"
        "/\n",
        encoding="utf-8",
    )

    out_dat = work_dir / f"{job_name}_FINAL_RESULTS_MMPBSA.dat"
    out_csv = work_dir / f"{job_name}_FINAL_RESULTS_MMPBSA.csv"
    log_out = work_dir / f"{job_name}_mmpbsa.stdout.log"
    log_err = work_dir / f"{job_name}_mmpbsa.stderr.log"

    # Use MPI if available for parallel frame analysis
    mpiexec = shutil.which("mpiexec") or shutil.which("mpirun")
    n_cores = _n_threads()
    if mpiexec and n_cores > 1:
        cmd = [
            mpiexec, "-np", str(n_cores),
            mmpbsa_bin, "MPI", "-O",
        ]
    else:
        cmd = [mmpbsa_bin, "-O"]

    cmd += [
        "-i", in_file.name,
        "-cs", tpr.name,
        "-ct", xtc.name,
        "-cp", top.name,
        "-ci", ndx.name,
        "-cg", str(rec_gid), str(lig_gid),
        "-cr", ref.name,
        "-o", out_dat.name,
        "-eo", out_csv.name,
    ]

    res = _run(cmd, cwd=work_dir, check=False, label="gmx_MMPBSA")
    log_out.write_text(res.stdout, encoding="utf-8", errors="replace")
    log_err.write_text(res.stderr, encoding="utf-8", errors="replace")

    # Success: outputs exist and calculation completed (PyQt5 GUI errors are non-fatal)
    calc_ok = (
        "[ERROR  ] = 0" in res.stderr
        or "Finalizing gmx_MMPBSA" in res.stderr
    )
    outputs_ok = out_dat.exists() and out_csv.exists()
    if not (outputs_ok and (calc_ok or res.returncode == 0)):
        tail = "\n".join(res.stderr.splitlines()[-30:])
        raise RuntimeError(
            f"gmx_MMPBSA failed (exit {res.returncode}). "
            f"Logs: {log_out}, {log_err}\n---\n{tail}"
        )

    return {
        "start_frame": start_frame,
        "end_frame": end_frame,
        "n_analyzed": n_analyzed,
        "out_dat": str(out_dat),
    }


def _parse_mmpbsa_results(dat_path: Path) -> Dict:
    content = dat_path.read_text(encoding="utf-8", errors="replace")
    results: Dict = {}

    if "NaN" in content:
        m = re.search(r"DELTA TOTAL\s+NaN", content)
        if m:
            results["DELTA TOTAL"] = float("nan")
            return results

    section = re.search(
        r"Delta \(Complex - Receptor - Ligand\):.*?-{5,}(.*?)-{5,}",
        content, re.DOTALL,
    )
    if section:
        txt = section.group(1)
        for key, pattern in [
            ("VDWAALS",      r"[ΔD]?VDWAALS\s+([-\d.]+)"),
            ("EEL",          r"[ΔD]?EEL\s+([-\d.]+)"),
            ("EGB",          r"[ΔD]?EGB\s+([-\d.]+)"),
            ("ESURF",        r"[ΔD]?ESURF\s+([-\d.]+)"),
            ("DELTA G gas",  r"[ΔD]?GGAS\s+([-\d.]+)"),
            ("DELTA G solv", r"[ΔD]?GSOLV\s+([-\d.]+)"),
            ("DELTA TOTAL",  r"[ΔD]?TOTAL\s+([-\d.]+)"),
        ]:
            m = re.search(pattern, txt)
            if m:
                results[key] = float(m.group(1))

    return results


# ── MD convergence statistics (gmx energy) ────────────────────────────────────

def _extract_energy_stat(
    edr: Path, work_dir: Path, term_input: str, gmx: str
) -> Optional[float]:
    """Run gmx energy and return mean of first column after time."""
    xvg = work_dir / "_tmp_energy.xvg"
    r = _run(
        [gmx, "energy", "-f", edr.name, "-o", xvg.name],
        cwd=work_dir,
        stdin_text=term_input + "\n0\n",
        check=False,
    )
    if r.returncode != 0 or not xvg.exists():
        return None
    vals = []
    try:
        with open(xvg) as f:
            for line in f:
                if line.startswith(("#", "@")):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    try:
                        vals.append(float(parts[1]))
                    except ValueError:
                        pass
    finally:
        xvg.unlink(missing_ok=True)
    return sum(vals) / len(vals) if vals else None


def _md_convergence_stats(work_dir: Path, job_name: str, gmx: str) -> Dict:
    """Extract average T, P, and potential energy from equilibration EDRs."""
    stats: Dict = {}

    nvt_edr = work_dir / f"{job_name}_nvt.edr"
    npt_edr = work_dir / f"{job_name}_npt.edr"
    md_edr  = work_dir / f"{job_name}_md.edr"

    if nvt_edr.exists():
        t = _extract_energy_stat(nvt_edr, work_dir, "16", gmx)   # Temperature
        if t is not None:
            stats["nvt_avg_temperature_k"] = round(t, 2)

    if npt_edr.exists():
        p = _extract_energy_stat(npt_edr, work_dir, "18", gmx)   # Pressure
        if p is not None:
            stats["npt_avg_pressure_bar"] = round(p, 3)
        d = _extract_energy_stat(npt_edr, work_dir, "24", gmx)   # Density
        if d is not None:
            stats["npt_avg_density_kg_m3"] = round(d, 1)

    if md_edr.exists():
        t = _extract_energy_stat(md_edr, work_dir, "16", gmx)
        if t is not None:
            stats["prod_avg_temperature_k"] = round(t, 2)
        e = _extract_energy_stat(md_edr, work_dir, "10", gmx)   # Potential
        if e is not None:
            stats["prod_avg_potential_energy_kj_mol"] = round(e, 1)

    return stats


# ── Main pipeline ──────────────────────────────────────────────────────────────

def _run_pipeline(inputs: dict) -> dict:
    complex_pdb     = str(inputs.get("complex_pdb", "")).strip()
    receptor_chains = str(inputs.get("receptor_chains", "H,L")).strip()
    ligand_chains   = str(inputs.get("ligand_chains", "B")).strip()
    forcefield      = str(inputs.get("forcefield", "amber99sb-ildn")).strip()
    water_model     = str(inputs.get("water_model", "tip3p")).strip()
    temperature_k   = float(inputs.get("temperature_k", 300.0))
    ion_conc        = float(inputs.get("ion_concentration", 0.15))
    production_ns   = float(inputs.get("production_ns", 10.0))
    discard_ns      = float(inputs.get("discard_ns", 1.0))
    igb             = int(inputs.get("igb", 5))
    interval        = int(inputs.get("mmpbsa_interval", 5))

    if not complex_pdb or "ATOM" not in complex_pdb:
        raise ValueError("complex_pdb must contain a PDB structure (ATOM records required)")
    if discard_ns >= production_ns:
        raise ValueError(
            f"discard_ns ({discard_ns}) must be < production_ns ({production_ns})"
        )

    gmx = _find_gmx()
    _progress(f"GROMACS binary: {gmx}")
    _progress(f"Threads: {_n_threads()}")
    _progress(
        f"Simulation: {production_ns} ns production at {temperature_k} K, "
        f"{ion_conc} M NaCl"
    )
    _progress(
        f"Chains: receptor={receptor_chains!r}, ligand={ligand_chains!r}"
    )

    base_dir = Path(os.getenv("GROMACS_WORKDIR", tempfile.gettempdir()))
    work_dir = Path(tempfile.mkdtemp(prefix="gromacs_mmpbsa_", dir=base_dir))
    job_name = "run"

    try:
        # Write input PDB (translate displaced chains back to receptor centroid)
        pdb_path = work_dir / "input_complex.pdb"
        pdb_path.write_text(_prepare_complex_pdb(complex_pdb), encoding="utf-8")

        # [1/9] Topology
        _progress("\n[1/9] Generating topology (pdb2gmx)…")
        _generate_topology(work_dir, job_name, pdb_path, forcefield, water_model, gmx)
        _progress("  ✓ Topology done")

        # [2/9] Box
        _progress("\n[2/9] Creating simulation box (editconf)…")
        _create_box(work_dir, job_name, gmx)
        _progress("  ✓ Box created")

        # [3/9] Solvation
        _progress("\n[3/9] Solvating (solvate)…")
        _solvate(work_dir, job_name, gmx)
        _progress("  ✓ Solvated")

        # [4/9] Ions
        _progress(f"\n[4/9] Adding ions ({ion_conc} M NaCl, genion)…")
        _add_ions(work_dir, job_name, ion_conc, gmx)
        _progress("  ✓ Ions added")

        # [5/9] Energy minimization
        _progress("\n[5/9] Energy minimization (steepest descent, up to 50k steps)…")
        _energy_minimization(work_dir, job_name, gmx)
        _progress("  ✓ EM converged")

        # [6/9] NVT
        nvt_ns = 1.0
        nvt_steps = 500_000   # 1 ns at dt=0.002 ps
        _progress(f"\n[6/9] NVT equilibration ({nvt_ns} ns at {temperature_k} K)…")
        _run_nvt(work_dir, job_name, temperature_k, nvt_steps, gmx)
        _progress("  ✓ NVT done")

        # [7/9] NPT
        npt_ns = 1.0
        npt_steps = 500_000
        _progress(f"\n[7/9] NPT equilibration ({npt_ns} ns, C-rescale barostat)…")
        _run_npt(work_dir, job_name, temperature_k, npt_steps, gmx)
        _progress("  ✓ NPT done")

        # [8/9] Production MD
        _progress(
            f"\n[8/9] Production MD ({production_ns} ns, Parrinello-Rahman, "
            f"reaction-field)…\n"
            f"  Estimated wall time: {production_ns * 6:.0f}–{production_ns * 24:.0f} min"
        )
        _run_production(work_dir, job_name, temperature_k, production_ns, gmx)
        _progress("  ✓ Production MD done")

        # [9a/9] Trajectory preparation
        _progress("\n[9/9a] Preparing trajectory (PBC removal + backbone fit)…")
        _prepare_trajectory(work_dir, job_name, gmx)
        _progress("  ✓ Trajectory ready")

        # [9b/9] Index file
        _progress("\n[9/9b] Building receptor/ligand index…")
        ref_pdb = work_dir / f"{job_name}_md_ref.pdb"
        ndx_path = work_dir / f"{job_name}_index.ndx"
        _create_chain_index(ref_pdb, ndx_path, receptor_chains, ligand_chains)
        _progress("  ✓ Index created")

        # [9c/9] Regenerate reference PDB (Receptor+Ligand only)
        _progress("\n[9/9c] Regenerating reference PDB for gmx_MMPBSA compatibility…")
        _regenerate_reference_pdb(work_dir, job_name, gmx)

        # [9d/9] MM/GBSA
        _progress(
            f"\n[9/9d] Running MM/GBSA (igb={igb}, discard={discard_ns} ns)…"
        )
        mmpbsa_meta = _run_mmpbsa(
            work_dir, job_name,
            ion_concentration=ion_conc,
            discard_ns=discard_ns,
            production_ns=production_ns,
            interval=interval,
            igb=igb,
            gmx=gmx,
        )
        _progress("  ✓ MM/GBSA done")

        # Parse results
        dat_path = Path(mmpbsa_meta["out_dat"])
        energy = _parse_mmpbsa_results(dat_path)

        delta_g = energy.get("DELTA TOTAL")
        if delta_g is not None and not math.isnan(delta_g):
            if delta_g < -5:
                interp = "Strong predicted binding affinity"
            elif delta_g < -2:
                interp = "Moderate predicted binding affinity"
            else:
                interp = "Weak predicted binding affinity"
            _progress(f"\n  ΔG_bind = {delta_g:.2f} kcal/mol — {interp}")
        else:
            interp = "Could not determine binding affinity"

        # MD convergence statistics
        _progress("\nCollecting MD convergence statistics…")
        convergence = _md_convergence_stats(work_dir, job_name, gmx)
        convergence.update({
            "production_ns": production_ns,
            "discard_ns": discard_ns,
            "n_frames_analyzed": mmpbsa_meta["n_analyzed"],
            "start_frame": mmpbsa_meta["start_frame"],
            "end_frame": mmpbsa_meta["end_frame"],
        })

        _progress("\n✓ Pipeline complete")
        return {
            "delta_g_bind": delta_g,
            "energy_decomposition": energy,
            "md_convergence": convergence,
        }

    finally:
        # Keep work dir on failure for debugging; clean up on success only
        # to avoid filling disk with large trajectory files.
        if (work_dir / f"{job_name}_FINAL_RESULTS_MMPBSA.dat").exists():
            try:
                shutil.rmtree(work_dir)
            except Exception:
                pass


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run_pipeline(inputs)
    except Exception as exc:
        import traceback
        json.dump(
            {"error": str(exc), "traceback": traceback.format_exc()},
            sys.stdout,
        )
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
