#!/usr/bin/env bash
# Setup script for RFdiffusion.
# Run once from the repo root or from tools/rfdiffusion/.
# Requires: Python 3.9+, git, internet access.
# GPU usage: set CUDA_VISIBLE_DEVICES or use CPU (slow).
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TOOL_DIR"

echo "=== RFdiffusion setup ==="
echo "Tool dir: $TOOL_DIR"

# ── 1. Clone the repo ──────────────────────────────────────────────────────────
if [ ! -d "RFdiffusion/.git" ]; then
  echo "Cloning RFdiffusion..."
  git clone https://github.com/RosettaCommons/RFdiffusion.git
else
  echo "RFdiffusion repo already present — skipping clone."
fi

# ── 2. Create venv ─────────────────────────────────────────────────────────────
# Use Python 3.9 or 3.10 (RFdiffusion is not compatible with 3.12+)
PYTHON_BIN="${PYTHON:-python3}"
PY_VERSION=$("$PYTHON_BIN" -c "import sys; print(sys.version_info.major*10+sys.version_info.minor)")
if [ "$PY_VERSION" -lt 39 ] || [ "$PY_VERSION" -gt 311 ]; then
  echo "ERROR: RFdiffusion requires Python 3.9–3.11. Found: $("$PYTHON_BIN" --version)"
  echo "Set PYTHON=/path/to/python3.10 and re-run."
  exit 1
fi

if [ ! -d ".venv/bin" ]; then
  echo "Creating venv..."
  "$PYTHON_BIN" -m venv .venv
else
  echo "Venv already present — skipping creation."
fi

VENV_PIP="$TOOL_DIR/.venv/bin/pip"
VENV_PY="$TOOL_DIR/.venv/bin/python3"

"$VENV_PIP" install -q --upgrade pip setuptools wheel

# ── 3. Install PyTorch ─────────────────────────────────────────────────────────
# Detect platform; fall back to CPU if no CUDA
if python3 -c "import torch; torch.cuda.is_available()" 2>/dev/null | grep -q True; then
  echo "CUDA detected — installing torch with CUDA 11.8 support..."
  "$VENV_PIP" install -q torch torchvision --index-url https://download.pytorch.org/whl/cu118
else
  echo "No CUDA detected — installing CPU torch (inference will be slow)..."
  "$VENV_PIP" install -q torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi

# numpy<2 is required for PyTorch < 2.2
"$VENV_PIP" install -q "numpy<2"

# ── 4. Install DGL ─────────────────────────────────────────────────────────────
echo "Installing DGL (CPU backend)..."
"$VENV_PIP" install -q dgl -f https://data.dgl.ai/wheels/repo.html || \
"$VENV_PIP" install -q dgl --extra-index-url https://data.dgl.ai/wheels/repo.html || \
echo "WARNING: DGL install failed — try manually: pip install dgl -f https://data.dgl.ai/wheels/repo.html"

# ── 5. Install SE3Transformer + RFdiffusion deps ──────────────────────────────
echo "Installing SE3Transformer..."
"$VENV_PIP" install -q "$TOOL_DIR/RFdiffusion/env/SE3Transformer" || \
  echo "WARNING: SE3Transformer install failed — check RFdiffusion/env/SE3Transformer"

echo "Installing RFdiffusion package..."
"$VENV_PIP" install -q -e "$TOOL_DIR/RFdiffusion"

# ── 6. Download model weights ──────────────────────────────────────────────────
mkdir -p "$TOOL_DIR/models"

download_if_missing() {
  local url="$1"
  local dest="$TOOL_DIR/models/$(basename "$url")"
  if [ -f "$dest" ]; then
    echo "  $dest already present — skipping."
  else
    echo "  Downloading $(basename "$url")..."
    curl -L --progress-bar -o "$dest" "$url"
  fi
}

echo "Downloading model weights (~1.5 GB total)..."
BASE_URL="http://files.ipd.uw.edu/pub/RFdiffusion"
download_if_missing "$BASE_URL/6f5902ac237024bdd0c176cb93063dc4/Base_ckpt.pt"
download_if_missing "$BASE_URL/e29311f6f1bf1af907f9ef9f44b8328b/Complex_base_ckpt.pt"
download_if_missing "$BASE_URL/60f09a193fb5e5ccdc4980417708dbab/Complex_Fold_base_ckpt.pt"

# ── 7. Patch SE3Transformer NVTX calls (required on CPU-only PyTorch) ─────────
echo "Patching SE3Transformer NVTX calls for CPU compatibility..."
VENV_PYTHON="$TOOL_DIR/.venv/bin/python3"
SE3_DIR="$TOOL_DIR/RFdiffusion/env/SE3Transformer"
for f in \
    "$SE3_DIR/se3_transformer/model/basis.py" \
    "$SE3_DIR/se3_transformer/model/layers/norm.py" \
    "$SE3_DIR/se3_transformer/model/layers/attention.py" \
    "$SE3_DIR/se3_transformer/model/layers/convolution.py"; do
  "$VENV_PYTHON" - "$f" << 'PYEOF'
import sys
path = sys.argv[1]
content = open(path).read()
old = 'from torch.cuda.nvtx import range as nvtx_range'
new = '''import contextlib as _cm, torch as _torch
if _torch.cuda.is_available():
    from torch.cuda.nvtx import range as nvtx_range
else:
    @_cm.contextmanager
    def nvtx_range(*a, **kw):
        yield'''
if old in content and 'contextlib as _cm' not in content:
    open(path, 'w').write(content.replace(old, new))
    print(f"  patched: {path.split('/')[-1]}")
else:
    print(f"  skip (already patched): {path.split('/')[-1]}")
PYEOF
done
# Clear .pyc cache so Python picks up the patched files
find "$TOOL_DIR" -name "*.pyc" -delete

echo ""
echo "=== Setup complete ==="
echo "Venv: $TOOL_DIR/.venv"
echo "Repo: $TOOL_DIR/RFdiffusion"
echo "Weights: $TOOL_DIR/models/"
echo ""
echo "Test: echo '{\"num_designs\":1,\"num_residues\":50}' | $TOOL_DIR/.venv/bin/python3 $TOOL_DIR/run.py"
