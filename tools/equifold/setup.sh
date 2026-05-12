#!/usr/bin/env bash
# EquiFold setup: clone repo and install extra deps into the shared superwater conda env.
# torch_scatter / torch_geometric / e3nn are already present in that env.
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$TOOL_DIR/repo"
CONDA_ENV="${EQUIFOLD_CONDA_ENV:-/Users/oswaldkid/miniforge3/envs/superwater}"

# ── 1. Clone repo ──────────────────────────────────────────────────────────────
if [ ! -d "$REPO_DIR/.git" ]; then
    echo "Cloning EquiFold…"
    git clone --depth=1 https://github.com/Genentech/equifold "$REPO_DIR"
else
    echo "Repo already present at $REPO_DIR"
fi

# ── 2. Patch openfold_light for NumPy ≥ 1.24 (np.int removed) ─────────────────
RESIDUE_CONSTANTS="$REPO_DIR/openfold_light/residue_constants.py"
if grep -q 'dtype=np\.int\b' "$RESIDUE_CONSTANTS" 2>/dev/null; then
    echo "Patching openfold_light/residue_constants.py (np.int → int)…"
    python3 -c "
content = open('$RESIDUE_CONSTANTS').read()
import re; content = re.sub(r'np\.int\b', 'int', content)
open('$RESIDUE_CONSTANTS', 'w').write(content)
"
fi

# ── 3. Install extra deps into the conda env if missing ───────────────────────
PYTHON="$CONDA_ENV/bin/python"
PIP="$CONDA_ENV/bin/pip"

"$PYTHON" -c "import pytorch_lightning" 2>/dev/null || {
    echo "Installing pytorch-lightning into $CONDA_ENV…"
    "$PIP" install -q "pytorch-lightning==2.1.0" "lightning==2.1.0" "setuptools==69.5.1"
}
"$PYTHON" -c "import einops" 2>/dev/null || "$PIP" install -q einops

# ── 4. Create .venv/bin/python wrapper that delegates to the conda env ─────────
# subprocess_runner looks for tools/equifold/.venv/bin/python.
# A symlink doesn't activate conda's site-packages, so we use a bash wrapper.
mkdir -p "$TOOL_DIR/.venv/bin"
cat > "$TOOL_DIR/.venv/bin/python" << WRAPPER
#!/usr/bin/env bash
exec "$PYTHON" "\$@"
WRAPPER
chmod +x "$TOOL_DIR/.venv/bin/python"

# ── 5. Smoke test ──────────────────────────────────────────────────────────────
echo "Smoke-testing imports…"
PYTHONPATH="$REPO_DIR" "$TOOL_DIR/.venv/bin/python" -c "
import sys, os
sys.path.insert(0, '$REPO_DIR')
os.chdir('$REPO_DIR')
import torch
from torch_geometric.data import Data
import e3nn
from models import NN
from utils_data import sequence_to_feats, x_to_pdb, collate_fn, cg_X0
assert cg_X0 is not None, 'cg_X0.npz not loaded — check working directory'
print(f'torch={torch.__version__} e3nn={e3nn.__version__}')
print('cg_X0 shape:', cg_X0.shape)
print('All imports OK.')
"
echo "EquiFold setup complete."
