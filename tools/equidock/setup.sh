#!/usr/bin/env bash
# EquiDock setup: create isolated venv, install compatible torch + DGL.
# The repo is expected at tools/equidock/repo/ (already cloned or cloned here).
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$TOOL_DIR/repo"
VENV_DIR="$TOOL_DIR/.venv"

# ── 1. Clone repo if needed ────────────────────────────────────────────────────
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning equidock_public…"
    git clone https://github.com/octavian-ganea/equidock_public "$REPO_DIR"
else
    echo "Repo already at $REPO_DIR, skipping clone."
fi

# ── 2. Pick Python (3.10 or 3.9) ──────────────────────────────────────────────
if command -v python3.10 &>/dev/null; then
    PYTHON=python3.10
elif command -v python3.9 &>/dev/null; then
    PYTHON=python3.9
else
    echo "ERROR: Python 3.9 or 3.10 required."
    exit 1
fi
echo "Using: $($PYTHON --version)"

# ── 3. Create venv ─────────────────────────────────────────────────────────────
$PYTHON -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip setuptools wheel certifi

CERT_PATH=$("$VENV_DIR/bin/python" -c "import certifi; print(certifi.where())")

# ── 4. Install PyTorch (CPU, compatible with Python 3.10) ─────────────────────
PY_VER=$("$VENV_DIR/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

if [[ "$PY_VER" == "3.10" || "$PY_VER" == "3.11" ]]; then
    # torch 1.10.x has no Python 3.10 wheels — use 2.0.x instead
    echo "Python $PY_VER: installing PyTorch 2.0.1 (CPU)…"
    SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
        "$VENV_DIR/bin/pip" install -q \
        "torch==2.0.1" \
        --index-url https://download.pytorch.org/whl/cpu
    TORCH_VER="2.0"
else
    echo "Python $PY_VER: installing PyTorch 1.10.2 (CPU)…"
    SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
        "$VENV_DIR/bin/pip" install -q \
        "torch==1.10.2" \
        --extra-index-url https://download.pytorch.org/whl/cpu
    TORCH_VER="1.10"
fi

# ── 5. Install DGL (CPU build matching torch version) ─────────────────────────
echo "Installing DGL (CPU, torch $TORCH_VER)…"
if [[ "$TORCH_VER" == "2.0" ]]; then
    SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
        "$VENV_DIR/bin/pip" install -q "dgl==1.1.3" \
        -f https://data.dgl.ai/wheels/torch-2.0/repo.html
else
    SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
        "$VENV_DIR/bin/pip" install -q "dgl==0.7.0" \
        --find-links https://data.dgl.ai/wheels/repo.html
fi

# ── 6. Install remaining requirements ─────────────────────────────────────────
echo "Installing other requirements…"
SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
    "$VENV_DIR/bin/pip" install -q \
    "numpy<2" \
    "biopandas==0.2.8" \
    "POT>=0.7.0" \
    "dgllife" \
    "joblib" \
    "scipy" \
    "rdkit-pypi"

# ── 7. Verify checkpoints ──────────────────────────────────────────────────────
DIPS_CKPT="$REPO_DIR/checkpts/oct20_Wdec_0.0001#ITS_lw_10.0#Hdim_64#Nlay_8#shrdLay_F#ln_LN#lnX_0#Hnrm_0#NattH_50#skH_0.75#xConnI_0.0#LkySl_0.01#pokOTw_1.0#fine_F#/dips_model_best.pth"
DB5_CKPT="$REPO_DIR/checkpts/oct20_Wdec_0.001#ITS_lw_10.0#Hdim_64#Nlay_5#shrdLay_T#ln_LN#lnX_0#Hnrm_0#NattH_50#skH_0.5#xConnI_0.0#LkySl_0.01#pokOTw_1.0#fine_F#/db5_model_best.pth"
for ckpt in "$DIPS_CKPT" "$DB5_CKPT"; do
    [ -f "$ckpt" ] && echo "✓ $(basename $(dirname $ckpt))" || echo "✗ MISSING: $ckpt"
done

# ── 8. Smoke test ──────────────────────────────────────────────────────────────
echo "Smoke-testing imports…"
PYTHONPATH="$REPO_DIR" "$VENV_DIR/bin/python" -c "
import sys; sys.path.insert(0, '$REPO_DIR')
import os; os.environ['DGLBACKEND'] = 'pytorch'
import torch, dgl, biopandas, numpy as np
print(f'torch={torch.__version__} dgl={dgl.__version__} numpy={np.__version__}')
from src.utils.protein_utils import preprocess_unbound_bound, protein_to_graph_unbound_bound
from src.utils.train_utils import batchify_and_create_hetero_graphs_inference, create_model
print('All imports OK.')
"
echo "OK — equidock setup complete."
