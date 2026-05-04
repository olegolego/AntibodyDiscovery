#!/usr/bin/env bash
# Create the PDBFixer tool environment.
# Run from the repo root: bash tools/pdbfixer/setup.sh
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Creating venv at $TOOL_DIR/.venv …"
python3 -m venv "$TOOL_DIR/.venv"

echo "Upgrading pip…"
"$TOOL_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel

echo "Installing pdbfixer (pulls in openmm)…"
# pdbfixer lives on the conda-forge PyPI mirror but openmm must be installed first.
# The easiest path on macOS/Linux without conda: use the OpenMM conda package;
# alternatively use the pip wheel from the openmm channel.
# We try pip first (works on many Linux/macOS builds); if it fails, guide the user.
"$TOOL_DIR/.venv/bin/pip" install pdbfixer || {
  echo ""
  echo "pip install failed. pdbfixer requires openmm, which is best installed via conda:"
  echo "  conda create -n pdbfixer -c conda-forge pdbfixer python=3.10"
  echo "  ln -sf \$(conda run -n pdbfixer which python) $TOOL_DIR/.venv/bin/python"
  echo "Or activate the conda env and point PDBFIXER_PYTHON to its python."
  exit 1
}

echo "Verifying…"
"$TOOL_DIR/.venv/bin/python" -c "from pdbfixer import PDBFixer; print('pdbfixer ok')"
echo "PDBFixer setup complete."
