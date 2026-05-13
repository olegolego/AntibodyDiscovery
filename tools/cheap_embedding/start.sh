#!/usr/bin/env bash
# Start the CHEAP Embedding HTTP server.
# Sources config.env for port and conda env path; all values can be overridden
# by environment variables for standalone use.
set -e

CONDA_ENV_BIN="${CHEAP_CONDA_ENV:-/Users/oswaldkid/miniforge3/envs/cheap}/bin"
PORT="${CHEAP_EMBEDDING_PORT:-8006}"

export PATH="$CONDA_ENV_BIN:$PATH"
export CHEAP_CACHE="${CHEAP_CACHE:-$HOME/.cache/cheap}"

echo "Starting CHEAP Embedding server on port $PORT"
echo "  Checkpoint cache: $CHEAP_CACHE"
echo "  First request loads ESMFold (~4 GB RAM, 30-90 s on CPU)"
cd "$(dirname "$0")"
exec "$CONDA_ENV_BIN/uvicorn" server:app --host 127.0.0.1 --port "$PORT"
