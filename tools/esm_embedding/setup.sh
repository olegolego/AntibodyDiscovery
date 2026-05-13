#!/usr/bin/env bash
# Set up ESM2 embedding tool.
# Creates a Python venv at tools/esm_embedding/.venv, installs CPU-only PyTorch
# and HuggingFace transformers, then pre-downloads all four ESM2 checkpoints.
#
# Usage:
#   bash tools/esm_embedding/setup.sh
#
# Environment variables:
#   PYTHON      — Python interpreter to use (default: python3.10)
#   HF_HOME     — Override HuggingFace cache dir (default: ~/.cache/huggingface)
set -e

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$TOOL_DIR/.venv"
PYTHON="${PYTHON:-python3.10}"

echo "══════════════════════════════════════════════"
echo "  ESM2 Embedding — setup"
echo "══════════════════════════════════════════════"

# ── Create venv ───────────────────────────────────────────────────────────────
echo ""
echo "── Creating venv at $VENV"
"$PYTHON" -m venv "$VENV"

# ── Install dependencies ──────────────────────────────────────────────────────
echo ""
echo "── Installing CPU PyTorch + transformers"
"$VENV/bin/pip" install --upgrade pip -q
"$VENV/bin/pip" install torch --index-url https://download.pytorch.org/whl/cpu -q
"$VENV/bin/pip" install "transformers>=4.30" -q

# ── Pre-download all ESM2 weights ─────────────────────────────────────────────
echo ""
echo "── Pre-downloading ESM2 checkpoints from HuggingFace"
echo "   (8M ~30 MB, 35M ~140 MB, 150M ~600 MB, 650M ~2.5 GB)"
echo "   Re-run to resume partial downloads."
echo ""

"$VENV/bin/python" - <<'PYEOF'
from transformers import EsmModel, EsmTokenizer

MODELS = [
    ("8M",   "facebook/esm2_t6_8M_UR50D"),
    ("35M",  "facebook/esm2_t12_35M_UR50D"),
    ("150M", "facebook/esm2_t30_150M_UR50D"),
    ("650M", "facebook/esm2_t33_650M_UR50D"),
]

for size, name in MODELS:
    print(f"  Downloading ESM2-{size} ({name})…")
    EsmTokenizer.from_pretrained(name)
    EsmModel.from_pretrained(name)
    print(f"  ✓ ESM2-{size} ready")

print("")
print("All ESM2 weights downloaded.")
PYEOF

echo ""
echo "── Smoke test (ESM2-8M, 11-residue sequence)…"
echo '{"sequence":"EVQLVESGGGL","model_size":"8M","pool_mode":"mean"}' \
  | "$VENV/bin/python" "$TOOL_DIR/run.py" \
  | "$VENV/bin/python" -c "
import json, sys
o = json.load(sys.stdin)
if 'error' in o:
    print('FAIL:', o['error']); sys.exit(1)
dim = len(o['embedding'])
print(f'  ✓ Embedding dim={dim} (expected 320)')
"

echo ""
echo "══════════════════════════════════════════════"
echo "  ESM2 embedding tool ready."
echo "  Interpreter: $VENV/bin/python"
echo "══════════════════════════════════════════════"
