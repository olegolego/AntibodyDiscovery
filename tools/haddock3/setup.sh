#!/usr/bin/env bash
# Create the HADDOCK3 tool environment.
# Run from the repo root: bash tools/haddock3/setup.sh
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Creating venv at $TOOL_DIR/.venv using python3.10..."
python3.10 -m venv "$TOOL_DIR/.venv"

echo "Upgrading pip/setuptools/wheel..."
"$TOOL_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel certifi

echo "Installing haddock3 + pdb-tools..."
CERT_PATH=$("$TOOL_DIR/.venv/bin/python" -c "import certifi; print(certifi.where())")
SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
  "$TOOL_DIR/.venv/bin/pip" install -r "$TOOL_DIR/requirements.txt"

echo "Verifying..."
"$TOOL_DIR/.venv/bin/haddock3" --version
"$TOOL_DIR/.venv/bin/python" -c "import pdbtools; print('pdb-tools ok')"
echo "HADDOCK3 setup complete."
