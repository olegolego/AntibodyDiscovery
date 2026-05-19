#!/usr/bin/env bash
# Set up IgLM tool.
#
# What this does:
#   1. Creates a Python 3.10 venv at tools/iglm/.venv
#   2. Installs CPU PyTorch + IgLM package
#   3. IgLM weights (~60 MB) are bundled inside the pip package — no extra download.
#   4. Runs a smoke test (log_likelihood on a short sequence).
#
# Usage:
#   bash tools/iglm/setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "══════════════════════════════════════════════"
echo "  IgLM — setup"
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

# ── IgLM (weights bundled inside the package) ─────────────────────────────────
echo ""
echo "── Installing IgLM (weights are bundled in the package, ~60 MB)"
"$PIP" install iglm -q
# transformers 5.x breaks BertTokenizer custom vocab loading — pin to 4.x
"$PIP" install "transformers>=4.6.1,<5.0" -q
# CDR boundary detection (abnumber wraps anarci for IMGT/Kabat/Chothia)
"$PIP" install abnumber anarci -q

# ── Smoke test ────────────────────────────────────────────────────────────────
echo ""
echo "── Running smoke test (log_likelihood on EVQLVES…)…"
"$PYTHON" - <<'PYEOF'
from iglm import IgLM
model = IgLM()
seq = "EVQLVESGG"
ll = model.log_likelihood(seq, chain_token="[HEAVY]", species_token="[HUMAN]")
print(f"  log_likelihood = {ll:.4f}  ✓")
PYEOF

echo ""
echo "══════════════════════════════════════════════"
echo "  IgLM ready."
echo "  Venv: $VENV"
echo ""
echo "  Quick test:"
echo "    echo '{\"mode\":\"log_likelihood\",\"sequence\":\"EVQLVESGG\"}' \\"
echo "    | $PYTHON tools/iglm/run.py"
echo "══════════════════════════════════════════════"
