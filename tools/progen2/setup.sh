#!/usr/bin/env bash
# Set up ProGen2 tool.
#
# What this does:
#   1. Creates a Python 3.10 venv at tools/progen2/.venv
#   2. Installs CPU PyTorch + transformers + tokenizers
#   3. Clones the Salesforce progen repo (model source code; not pip-installable)
#   4. Downloads progen2-oas checkpoint (~3 GB) from Google Storage
#   5. Runs a smoke test (log_likelihood on a short sequence)
#
# Usage:
#   bash tools/progen2/setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PROGEN_SRC="$SCRIPT_DIR/progen_src"
CKPT_DIR="$SCRIPT_DIR/checkpoints"

echo "══════════════════════════════════════════════"
echo "  ProGen2 — setup"
echo "══════════════════════════════════════════════"

# ── Create venv ───────────────────────────────────────────────────────────────
if [ -d "$VENV" ]; then
  echo "── venv already exists — skipping creation"
else
  echo "── Creating venv (Python 3.10)"
  python3.10 -m venv "$VENV"
fi

PIP="$VENV/bin/pip"
PYTHON="$VENV/bin/python"

echo ""
echo "── Upgrading pip"
"$PIP" install --upgrade pip -q

# ── CPU PyTorch ───────────────────────────────────────────────────────────────
echo ""
echo "── Installing CPU PyTorch"
"$PIP" install torch --index-url https://download.pytorch.org/whl/cpu -q

# ── transformers + tokenizers ─────────────────────────────────────────────────
echo ""
echo "── Installing transformers + tokenizers"
"$PIP" install "transformers>=4.26,<5.0" tokenizers -q
"$PIP" install scipy -q  # used by some ProGen2 utilities

# ── Clone progen repo (model source code) ─────────────────────────────────────
echo ""
if [ -d "$PROGEN_SRC" ]; then
  echo "── progen source already cloned — skipping"
else
  echo "── Cloning salesforce/progen (model source, no weights)"
  git clone --depth=1 https://github.com/salesforce/progen.git "$PROGEN_SRC"
fi

# ── Download progen2-oas checkpoint ───────────────────────────────────────────
echo ""
CKPT_PATH="$CKPT_DIR/progen2-oas"
if [ -d "$CKPT_PATH" ] && [ -f "$CKPT_PATH/pytorch_model.bin" ]; then
  echo "── progen2-oas checkpoint already exists — skipping download"
else
  mkdir -p "$CKPT_DIR"
  echo "── Downloading progen2-oas checkpoint (~3 GB)…"
  TARBALL="$CKPT_DIR/progen2-oas.tar.gz"
  curl -L -o "$TARBALL" \
    "https://storage.googleapis.com/sfr-progen-research/checkpoints/progen2-oas.tar.gz"
  echo "── Extracting…"
  # The tar.gz has no top-level directory — extract into a named subdir
  mkdir -p "$CKPT_PATH"
  tar -xzf "$TARBALL" -C "$CKPT_PATH"
  # If tar extracted without a subdir wrapper, files land directly in CKPT_PATH
  # If it extracted into an extra level, move them up
  INNER=$(ls "$CKPT_PATH" | head -1)
  if [ -d "$CKPT_PATH/$INNER" ] && [ -f "$CKPT_PATH/$INNER/config.json" ]; then
    mv "$CKPT_PATH/$INNER"/* "$CKPT_PATH/"
    rmdir "$CKPT_PATH/$INNER"
  fi
  rm -f "$TARBALL"
  echo "── progen2-oas checkpoint ready at $CKPT_PATH"
fi

# ── Download progen2-medium checkpoint (optional, skip by default) ────────────
# Uncomment to also download the general-purpose medium model:
# CKPT_PATH_MED="$CKPT_DIR/progen2-medium"
# if [ -d "$CKPT_PATH_MED" ]; then
#   echo "── progen2-medium checkpoint already exists"
# else
#   echo "── Downloading progen2-medium checkpoint (~3 GB)…"
#   TARBALL_MED="$CKPT_DIR/progen2-medium.tar.gz"
#   curl -L -o "$TARBALL_MED" \
#     "https://storage.googleapis.com/sfr-progen-research/checkpoints/progen2-medium.tar.gz"
#   tar -xzf "$TARBALL_MED" -C "$CKPT_DIR"
#   rm -f "$TARBALL_MED"
# fi

# ── Smoke test ────────────────────────────────────────────────────────────────
echo ""
echo "── Running smoke test (log_likelihood on short sequence)…"
"$PYTHON" - <<PYEOF
import sys, os, json
# Add progen source to path
sys.path.insert(0, "$PROGEN_SRC/progen2")

from models.progen.modeling_progen import ProGenForCausalLM
from models.progen.configuration_progen import ProGenConfig
from tokenizers import Tokenizer
import torch

tokenizer = Tokenizer.from_file("$PROGEN_SRC/progen2/tokenizer.json")

ckpt_dir = "$CKPT_DIR/progen2-oas"
with open(f"{ckpt_dir}/config.json") as f:
    cfg_dict = json.load(f)
cfg_dict.pop("architectures", None)
cfg_dict.pop("model_type", None)
config = ProGenConfig(**cfg_dict)

print(f"  Loading weights from {ckpt_dir}…", file=sys.stderr)
model = ProGenForCausalLM(config)
state_dict = torch.load(f"{ckpt_dir}/pytorch_model.bin", map_location="cpu")
model.load_state_dict(state_dict)
model.eval()

seq = "EVQLVESGGGLVQ"
token_ids = tokenizer.encode("1" + seq + "2").ids
input_ids = torch.tensor([token_ids])
with torch.no_grad():
    out = model(input_ids, labels=input_ids)
ll = -out.loss.item()
print(f"  log_likelihood = {ll:.4f}  ✓")
PYEOF

echo ""
echo "══════════════════════════════════════════════"
echo "  ProGen2 ready."
echo "  Venv:       $VENV"
echo "  Checkpoint: $CKPT_PATH"
echo ""
echo "  Quick test:"
echo '    echo '"'"'{"mode":"log_likelihood","sequence":"EVQLVESGG"}'"'"' \'
echo "    | $PYTHON tools/progen2/run.py"
echo "══════════════════════════════════════════════"
