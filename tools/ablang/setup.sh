#!/usr/bin/env bash
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

python3.10 -m venv "$TOOL_DIR/.venv"
"$TOOL_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel certifi

CERT_PATH=$("$TOOL_DIR/.venv/bin/python" -c "import certifi; print(certifi.where())")
SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
  "$TOOL_DIR/.venv/bin/pip" install -q \
    "ablang" \
    "numpy<2"

# Pre-download model weights so they're ready at runtime
echo "Pre-downloading AbLang heavy-chain weights…"
"$TOOL_DIR/.venv/bin/python" -c "
import ablang
m = ablang.pretrained('heavy')
m.freeze()
print('Heavy chain model ready.')
"

echo "Pre-downloading AbLang light-chain weights…"
"$TOOL_DIR/.venv/bin/python" -c "
import ablang
m = ablang.pretrained('light')
m.freeze()
print('Light chain model ready.')
"

echo "OK"
