#!/usr/bin/env bash
# ImmuneBuilder currently shares the backend venv (no dep conflicts).
# This script installs it there. Run from repo root: bash tools/immunebuilder/setup.sh
set -e
BACKEND_VENV="$(cd "$(dirname "$0")/../.." && pwd)/backend/.venv"

if [ ! -d "$BACKEND_VENV" ]; then
  echo "Backend venv not found at $BACKEND_VENV"
  echo "Run: cd backend && python3.10 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

echo "Installing ImmuneBuilder into $BACKEND_VENV..."
"$BACKEND_VENV/bin/pip" install ImmuneBuilder anarci

echo "Verifying..."
"$BACKEND_VENV/bin/python" -c "from ImmuneBuilder import ABodyBuilder2; print('ImmuneBuilder ok')"
"$BACKEND_VENV/bin/python" -c "import anarci; print('ANARCI ok')"

echo "Pre-downloading model weights (runs once, ~200 MB)..."
"$BACKEND_VENV/bin/python" -c "
from ImmuneBuilder import ABodyBuilder2
print('Initialising ABodyBuilder2 (downloads weights if needed)...')
b = ABodyBuilder2(model_ids=[1])
print('Weights ready.')
"
echo "ImmuneBuilder setup complete."
