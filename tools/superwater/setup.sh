#!/usr/bin/env bash
# Create the SuperWater tool environment and clone the repo.
# Run from the repo root: bash tools/superwater/setup.sh
#
# Requires: conda (miniforge / mambaforge / miniconda3 / anaconda3)
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

# ── Clone SuperWater repo ─────────────────────────────────────────────────────
REPO_DIR="$TOOL_DIR/SuperWater"
if [ ! -d "$REPO_DIR" ]; then
  echo "Cloning SuperWater repo…"
  git clone https://github.com/kuangxh9/SuperWater.git "$REPO_DIR"
else
  echo "SuperWater repo already exists at $REPO_DIR — skipping clone"
fi

# ── Create conda environment ──────────────────────────────────────────────────
ENV_NAME="superwater"
if "$CONDA_CMD" env list | grep -q "^$ENV_NAME "; then
  echo "Conda env '$ENV_NAME' already exists — skipping creation"
else
  echo "Creating conda env '$ENV_NAME' with Python 3.10…"
  "$CONDA_CMD" create -n "$ENV_NAME" python=3.10 -y -q
fi

CONDA_PY="$CONDA_ROOT/envs/$ENV_NAME/bin/python"
CONDA_PIP="$CONDA_ROOT/envs/$ENV_NAME/bin/pip"

# ── Install PyTorch 2.5.1 (CPU build — GPU optional) ─────────────────────────
echo "Installing PyTorch 2.5.1…"
"$CONDA_PIP" install -q torch==2.5.1 torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# ── Install torch-geometric ───────────────────────────────────────────────────
echo "Installing torch-geometric…"
"$CONDA_PIP" install -q torch-geometric

# ── Install fair-esm (ESM2 embeddings) ───────────────────────────────────────
echo "Installing fair-esm…"
"$CONDA_PIP" install -q fair-esm

# ── Install remaining dependencies ───────────────────────────────────────────
echo "Installing rdkit (conda-forge)…"
"$CONDA_CMD" install -n "$ENV_NAME" -c conda-forge rdkit openbabel -y -q

echo "Installing biopython, scikit-learn, wandb, pandas, and other deps…"
"$CONDA_PIP" install -q biopython numpy scipy scikit-learn wandb tqdm pyyaml pandas

echo "Installing torch extensions for torch 2.5.1 CPU…"
"$CONDA_PIP" install -q torch-cluster torch-scatter torch-sparse \
  -f https://data.pyg.org/whl/torch-2.5.1+cpu.html

echo "Installing torch-geometric 2.6.1 (pinned — 2.7+ has iteration API changes)…"
"$CONDA_PIP" install -q "torch-geometric==2.6.1"

echo "Installing e3nn 0.5.3, einops, spyrmsd, opt-einsum…"
"$CONDA_PIP" install -q "e3nn==0.5.3" einops spyrmsd opt-einsum

# ── Clone ESM repo (provides esm/scripts/extract.py required for embeddings) ──
ESM_DIR="$REPO_DIR/esm"
if [ ! -d "$ESM_DIR" ]; then
  echo "Cloning ESM repo into SuperWater/esm/…"
  git clone --depth 1 https://github.com/facebookresearch/esm.git "$ESM_DIR"
else
  echo "ESM repo already exists at $ESM_DIR — skipping clone"
fi

if [ ! -f "$ESM_DIR/scripts/extract.py" ]; then
  echo "WARNING: esm/scripts/extract.py not found — ESM embedding step may fail"
fi

# ── Install repo package if setup.py/pyproject.toml exists ───────────────────
if [ -f "$REPO_DIR/setup.py" ] || [ -f "$REPO_DIR/pyproject.toml" ]; then
  echo "Installing SuperWater package (editable)…"
  "$CONDA_PIP" install -q -e "$REPO_DIR"
fi

# ── Verify model weights ──────────────────────────────────────────────────────
WORKDIR="$REPO_DIR/workdir"
if [ ! -d "$WORKDIR" ]; then
  echo ""
  echo "WARNING: $WORKDIR not found."
  echo "The SuperWater model weights live in the workdir/ folder of the repo."
  echo "If the repo was cloned without LFS, download weights manually:"
  echo "  cd $REPO_DIR && git lfs pull"
  echo "  # or follow instructions in the repo README"
fi

echo ""
echo "Verifying installation…"
"$CONDA_PY" -c "import torch; print('torch', torch.__version__)"
"$CONDA_PY" -c "import torch_geometric; print('torch-geometric ok')"
"$CONDA_PY" -c "import esm; print('fair-esm ok')"
"$CONDA_PY" -c "import Bio; print('biopython ok')"

echo ""
echo "SuperWater setup complete."
echo "Python: $CONDA_PY"
echo "Repo:   $REPO_DIR"
