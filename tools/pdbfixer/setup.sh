#!/usr/bin/env bash
# Create the PDBFixer tool environment via conda-forge (openmm requires conda).
# Run from the repo root: bash tools/pdbfixer/setup.sh
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Locate conda ──────────────────────────────────────────────────────────────
CONDA_CMD=""
for root in "$HOME/miniforge3" "$HOME/mambaforge" "$HOME/miniconda3" "$HOME/anaconda3"; do
  if [ -f "$root/bin/conda" ]; then
    CONDA_CMD="$root/bin/conda"
    CONDA_ROOT="$root"
    break
  fi
done

if [ -z "$CONDA_CMD" ]; then
  echo "ERROR: conda not found. Install miniforge3:"
  echo "  https://github.com/conda-forge/miniforge#install"
  exit 1
fi

echo "Using conda at: $CONDA_CMD"

# ── Create conda environment ──────────────────────────────────────────────────
ENV_NAME="pdbfixer"
if "$CONDA_CMD" env list | grep -q "^$ENV_NAME "; then
  echo "Conda env '$ENV_NAME' already exists — skipping creation"
else
  echo "Creating conda env '$ENV_NAME' with pdbfixer from conda-forge…"
  "$CONDA_CMD" create -n "$ENV_NAME" -c conda-forge pdbfixer python=3.10 -y -q
fi

CONDA_PY="$CONDA_ROOT/envs/$ENV_NAME/bin/python"

echo "Verifying…"
"$CONDA_PY" -c "from pdbfixer import PDBFixer; print('pdbfixer ok')"
"$CONDA_PY" -c "import openmm; print('openmm', openmm.__version__)"

echo "PDBFixer setup complete."
echo "Python: $CONDA_PY"
