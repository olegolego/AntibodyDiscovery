#!/usr/bin/env bash
# LigandMPNN setup script — creates isolated venv and installs the tool.
# https://github.com/dauparas/LigandMPNN
# Paper: Dauparas et al. 2025, Nat. Methods (doi:10.1038/s41592-024-02487-0)
set -e

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== LigandMPNN Setup ==="
echo "Tool dir: $TOOL_DIR"

# 1. Create venv
python3 -m venv "$TOOL_DIR/.venv"
"$TOOL_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel

# 2. Clone LigandMPNN repo if not already present
if [ ! -d "$TOOL_DIR/src" ]; then
    echo "Cloning LigandMPNN from GitHub..."
    git clone https://github.com/dauparas/LigandMPNN.git "$TOOL_DIR/src"
fi

# 3. Install requirements
echo "Installing Python dependencies..."
"$TOOL_DIR/.venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
"$TOOL_DIR/.venv/bin/pip" install -q prody biopython

# 4. Download model weights
echo "Downloading model weights (this may take a few minutes)..."
cd "$TOOL_DIR/src"
bash get_model_params.sh "./model_params"

echo ""
echo "=== LigandMPNN installed successfully ==="
echo "Set LIGAND_MPNN_SRC=$TOOL_DIR/src in your environment if needed."
echo "OK"
