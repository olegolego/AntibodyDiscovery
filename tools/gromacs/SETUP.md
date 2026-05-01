# GROMACS MD + MM/GBSA — Setup

## System Requirements

| Binary | Source | Notes |
|--------|--------|-------|
| `gmx` | GROMACS 2020+ | Automatically detected at `/mnt/ramdisk/miniconda3/envs/mmpbsa/` or on PATH |
| `gmx_MMPBSA` | gmx_MMPBSA 1.6+ | Must be on PATH; supports MPI for parallel frame analysis |
| `cpptraj` | AmberTools 22+ | Required by gmx_MMPBSA |
| `mpiexec` / `mpirun` | OpenMPI or MPICH | Optional — used for parallel MM/GBSA frames |

## Recommended: conda mmpbsa environment

```bash
conda create -n mmpbsa python=3.10
conda activate mmpbsa

conda install -c conda-forge gromacs=2024.1
conda install -c conda-forge gmx_mmpbsa
conda install -c conda-forge ambertools openmpi
```

## Python venv (for the subprocess runner)

```bash
cd tools/gromacs
bash setup.sh
```

This installs numpy, matplotlib, and optionally MDAnalysis into `tools/gromacs/.venv`.

## Starting the backend with GROMACS on PATH

The backend subprocess inherits the parent shell environment. Start it with the
conda env active so `gmx`, `gmx_MMPBSA`, and `cpptraj` are on PATH:

```bash
conda activate mmpbsa
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Or export PATH explicitly in your systemd/supervisor unit:

```
Environment="PATH=/mnt/ramdisk/miniconda3/envs/mmpbsa/bin:/usr/local/bin:/usr/bin:/bin"
```

## Optional: large work directory

MD trajectories can be several GB. By default the tool uses `tempfile.gettempdir()` (`/tmp`).
Override with an env var before starting the backend:

```bash
export GROMACS_WORKDIR=/scratch/gromacs_runs
```

## Typical runtime

| Production length | Approx wall time (32-core CPU) |
|---|---|
| 10 ns | 2–4 h |
| 50 ns | 8–16 h |
| 100 ns | 16–24 h |

## Input chains

When wiring from HADDOCK3:
- `receptor_chains` = antibody chains, typically `H,L` (or `H` for nanobody)
- `ligand_chains` = antigen chain, typically `B` (HADDOCK3 assigns chain B)

When wiring from EquiDock, same convention applies.

## Verify the installation

```bash
conda activate mmpbsa
gmx --version
gmx_MMPBSA --version
cpptraj --version
mpiexec --version   # optional
```

All four should print version information without errors.
