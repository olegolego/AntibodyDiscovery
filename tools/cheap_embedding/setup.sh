#!/usr/bin/env bash
# Set up CHEAP Embedding tool.
#
# What this does:
#   1. Creates a conda env named 'cheap' (Python 3.10, CPU-only PyTorch)
#   2. Installs CHEAP from GitHub and all runtime deps (fair-esm, openfold stub, etc.)
#   3. Downloads the default CHEAP checkpoint (shorten=1, dim=64, ~1 GB)
#      The ESMFold backbone (~8 GB, ESM2-3B) downloads on first /embed request.
#
# MEMORY REQUIREMENT:
#   First inference loads Meta ESMFold 3B (~8 GB RAM, 30-90 s on CPU).
#   Requires 16+ GB free RAM. If running the full platform stack, stop other
#   GPU-heavy services before sending the first embedding request.
#
# Usage:
#   bash tools/cheap_embedding/setup.sh
#
# Platform note:
#   Tested on macOS (Apple Silicon / x86) with CPU-only PyTorch.
#   On Linux with CUDA, replace the torch install line with the CUDA variant.
set -e

CONDA="${CONDA_PREFIX:-/Users/oswaldkid/miniforge3}"
ENV_NAME="cheap"
CACHE="${CHEAP_CACHE:-$HOME/.cache/cheap}"

echo "══════════════════════════════════════════════"
echo "  CHEAP Embedding — setup"
echo "══════════════════════════════════════════════"

# ── Create conda env (skip if already exists) ────────────────────────────────
echo ""
if "$CONDA/bin/conda" env list | grep -q "^${ENV_NAME} "; then
  echo "── Conda env '$ENV_NAME' already exists — skipping creation"
else
  echo "── Creating conda env '$ENV_NAME' (Python 3.10)"
  "$CONDA/bin/conda" create -n "$ENV_NAME" python=3.10 -y
fi

PYTHON="$CONDA/envs/$ENV_NAME/bin/python"
PIP="$CONDA/envs/$ENV_NAME/bin/pip"

echo ""
echo "── Upgrading pip"
"$PIP" install --upgrade pip -q

# ── PyTorch (CPU) ─────────────────────────────────────────────────────────────
echo ""
echo "── Installing CPU PyTorch"
echo "   (Linux + CUDA users: replace with the CUDA torch wheel for faster inference)"
"$PIP" install torch --index-url https://download.pytorch.org/whl/cpu -q

# ── Core runtime dependencies ─────────────────────────────────────────────────
echo ""
echo "── Installing core runtime dependencies"
"$PIP" install "transformers>=4.30" -q
"$PIP" install "lightning>=2.0" -q
"$PIP" install "hydra-core>=1.3" "omegaconf" "einops" -q
"$PIP" install biopython safetensors h5py biotite -q
"$PIP" install fastapi "uvicorn[standard]" -q
"$PIP" install pandas -q

# wandb is imported at module level by CHEAP's trainer
"$PIP" install wandb -q

# ── Meta fair-esm (CHEAP's ESMFold backbone uses this, not HuggingFace) ──────
echo ""
echo "── Installing Meta fair-esm (ESMFold backbone)"
"$PIP" install fair-esm -q

# ── Extra deps pulled in by CHEAP's openfold_utils ───────────────────────────
echo ""
echo "── Installing CHEAP openfold_utils dependencies"
"$PIP" install dm-tree ml-collections -q

# ── Install CHEAP from GitHub ─────────────────────────────────────────────────
echo ""
echo "── Installing CHEAP from GitHub"
"$PIP" install --no-deps git+https://github.com/amyxlu/cheap-proteins.git

# ── Install openfold stub ─────────────────────────────────────────────────────
# CHEAP's esmfold submodule imports openfold at module level (structure module,
# triangular attention) even though the embedding path never calls those classes.
# We install a minimal stub package to satisfy the import-time dependencies.
echo ""
echo "── Installing openfold stub (satisfies import-time deps only)"

SITE="$CONDA/envs/$ENV_NAME/lib/python3.10/site-packages"

# attn_core_inplace_cuda — CUDA attention kernel, not used on CPU
cat > "$SITE/attn_core_inplace_cuda.py" << 'PYEOF'
"""Stub for CUDA attention kernel — not needed on CPU / embedding-only path."""
def forward_(*args, **kwargs):
    raise NotImplementedError("attn_core_inplace_cuda stub — CUDA not available")
PYEOF

mkdir -p "$SITE/openfold/model" "$SITE/openfold/np" "$SITE/openfold/utils"
touch "$SITE/openfold/__init__.py" "$SITE/openfold/model/__init__.py" \
      "$SITE/openfold/np/__init__.py" "$SITE/openfold/utils/__init__.py"

cat > "$SITE/openfold/model/primitives.py" << 'PYEOF'
"""Openfold primitives stub."""
import torch.nn as nn
Linear = nn.Linear
LayerNorm = nn.LayerNorm
def ipa_point_weights_init_(weights): pass
PYEOF

cat > "$SITE/openfold/model/triangular_attention.py" << 'PYEOF'
"""Openfold triangular attention stub."""
import torch.nn as nn
class TriangleAttentionStartingNode(nn.Module):
    def __init__(self, *a, **kw): super().__init__()
    def forward(self, *a, **kw): raise NotImplementedError("openfold stub")
class TriangleAttentionEndingNode(nn.Module):
    def __init__(self, *a, **kw): super().__init__()
    def forward(self, *a, **kw): raise NotImplementedError("openfold stub")
PYEOF

cat > "$SITE/openfold/model/triangular_multiplicative_update.py" << 'PYEOF'
"""Openfold triangular multiplicative update stub."""
import torch.nn as nn
class TriangleMultiplicationIncoming(nn.Module):
    def __init__(self, *a, **kw): super().__init__()
    def forward(self, *a, **kw): raise NotImplementedError("openfold stub")
class TriangleMultiplicationOutgoing(nn.Module):
    def __init__(self, *a, **kw): super().__init__()
    def forward(self, *a, **kw): raise NotImplementedError("openfold stub")
PYEOF

cat > "$SITE/openfold/np/residue_constants.py" << 'PYEOF'
"""Openfold residue constants stub — shapes match real openfold for StructureModule init."""
import numpy as np
restype_rigid_group_default_frame = np.zeros((21, 8, 4, 4), dtype=np.float32)
restype_atom14_to_rigid_group = np.zeros((21, 14), dtype=np.int32)
restype_atom14_mask = np.zeros((21, 14), dtype=np.float32)
restype_atom14_rigid_group_positions = np.zeros((21, 14, 3), dtype=np.float32)
PYEOF

cat > "$SITE/openfold/utils/feats.py" << 'PYEOF'
"""Openfold feats stub."""
def frames_and_literature_positions_to_atom14_pos(*a, **kw): raise NotImplementedError("openfold stub")
def torsion_angles_to_frames(*a, **kw): raise NotImplementedError("openfold stub")
PYEOF

cat > "$SITE/openfold/utils/precision_utils.py" << 'PYEOF'
"""Openfold precision_utils stub."""
def is_fp16_enabled(): return False
PYEOF

cat > "$SITE/openfold/utils/rigid_utils.py" << 'PYEOF'
"""Openfold rigid_utils stub."""
class Rotation:
    def __init__(self, *a, **kw): raise NotImplementedError("openfold stub")
class Rigid:
    def __init__(self, *a, **kw): raise NotImplementedError("openfold stub")
PYEOF

cat > "$SITE/openfold/utils/tensor_utils.py" << 'PYEOF'
"""Openfold tensor_utils stub."""
def dict_multimap(fn, dicts): return {k: fn([d[k] for d in dicts]) for k in dicts[0]}
def permute_final_dims(tensor, inds):
    zero_index = -1 * len(inds)
    first_inds = list(range(len(tensor.shape[:zero_index])))
    return tensor.permute(first_inds + [zero_index + i for i in inds])
def flatten_final_dims(t, no_dims): return t.reshape(t.shape[:-no_dims] + (-1,))
PYEOF

cat > "$SITE/openfold/utils/loss.py" << 'PYEOF'
"""Openfold loss stub."""
def backbone_loss(*a, **kw): raise NotImplementedError("openfold stub")
PYEOF

echo "   ✓ openfold stub installed"

# ── Pre-download CHEAP checkpoint (hourglass model only, not ESMFold) ─────────
echo ""
echo "── Pre-downloading CHEAP checkpoint: shorten=1, dim=64 (~1 GB)"
echo "   Saving to: $CACHE"
mkdir -p "$CACHE"

CHEAP_CACHE="$CACHE" "$PYTHON" - <<PYEOF
import os, sys
os.environ['CHEAP_CACHE'] = '$CACHE'
from cheap.pretrained import CHEAP_shorten_1_dim_64
print("  Downloading CHEAP hourglass checkpoint (shorten=1, dim=64)…")
# return_pipeline=False downloads only the hourglass model, NOT ESMFold backbone
_ = CHEAP_shorten_1_dim_64(return_pipeline=False, model_dir='$CACHE', infer_mode=True)
print("  ✓ CHEAP shorten=1 dim=64 hourglass model ready")
PYEOF

# ── Pre-download ESMFold backbone (avoids long blocking download on first request) ──
# These are the Meta fair-esm models used by CHEAP's ESMFoldEmbed backbone.
# Total: ~8 GB. First /embed would time out without these pre-downloaded.
echo ""
echo "── Pre-downloading ESMFold backbone models (~8 GB total)"
echo "   This is the ESM2-3B + ESMFold trunk used by CHEAP — downloads once."
HUB_CACHE="$HOME/.cache/torch/hub/checkpoints"
mkdir -p "$HUB_CACHE"

# ESMFold state dict (~2.6 GB) — folding trunk weights
if [ ! -f "$HUB_CACHE/esmfold_3B_v1.pt" ]; then
  echo "   Downloading esmfold_3B_v1.pt (~2.6 GB)…"
  curl -L --retry 5 --retry-delay 3 \
    "https://dl.fbaipublicfiles.com/fair-esm/models/esmfold_3B_v1.pt" \
    -o "$HUB_CACHE/esmfold_3B_v1.pt" --progress-bar
  echo "   ✓ esmfold_3B_v1.pt"
else
  echo "   esmfold_3B_v1.pt already cached — skipping"
fi

# ESM2-3B language model (~5.3 GB)
if [ ! -f "$HUB_CACHE/esm2_t36_3B_UR50D.pt" ]; then
  echo "   Downloading esm2_t36_3B_UR50D.pt (~5.3 GB)…"
  curl -L --retry 5 --retry-delay 3 \
    "https://dl.fbaipublicfiles.com/fair-esm/models/esm2_t36_3B_UR50D.pt" \
    -o "$HUB_CACHE/esm2_t36_3B_UR50D.pt" --progress-bar
  echo "   ✓ esm2_t36_3B_UR50D.pt"
else
  echo "   esm2_t36_3B_UR50D.pt already cached — skipping"
fi

# Contact regression file (tiny, from regression/ not models/)
if [ ! -f "$HUB_CACHE/esm2_t36_3B_UR50D-contact-regression.pt" ]; then
  echo "   Downloading contact regression file…"
  curl -L --retry 3 \
    "https://dl.fbaipublicfiles.com/fair-esm/regression/esm2_t36_3B_UR50D-contact-regression.pt" \
    -o "$HUB_CACHE/esm2_t36_3B_UR50D-contact-regression.pt" --progress-bar
  echo "   ✓ contact regression"
else
  echo "   contact regression already cached — skipping"
fi

echo ""
echo "   ✓ All ESMFold backbone files ready (~8 GB, loads in ~60-90 s on CPU)"

# ── Verify all server imports ─────────────────────────────────────────────────
echo ""
echo "── Verifying server imports…"
cd "$(dirname "$0")"
CHEAP_CACHE="$CACHE" "$PYTHON" -c "
import sys; sys.path.insert(0, '.')
from cheap import pretrained
from cheap.pretrained import CHEAP_shorten_1_dim_64
import fastapi, uvicorn
print('  ✓ All imports OK')
"

echo ""
echo "══════════════════════════════════════════════"
echo "  CHEAP embedding tool ready."
echo ""
echo "  Start server:   bash tools/cheap_embedding/start.sh"
echo "  Checkpoint dir: $CACHE"
echo "  Conda env:      $CONDA/envs/$ENV_NAME"
echo ""
echo "  MEMORY: First /embed request downloads and loads ESMFold 3B (~8 GB)."
echo "          Ensure 16+ GB RAM is free before the first request."
echo ""
echo "  Pre-download more checkpoints (optional):"
echo "    CHEAP_CACHE=$CACHE \\"
echo "    $PYTHON -c \\"
echo "      'from cheap.pretrained import CHEAP_shorten_2_dim_32; \\"
echo "       CHEAP_shorten_2_dim_32(return_pipeline=False, model_dir=\"$CACHE\")'"
echo "══════════════════════════════════════════════"
