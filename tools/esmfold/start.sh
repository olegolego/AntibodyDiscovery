#!/usr/bin/env bash
# Start the ESMFold HTTP server.
# Paths and port come from environment variables set by the root start.sh
# (which sources config.env). Fallbacks are provided for standalone use.
set -e

CONDA_ENV_BIN="${ESMFOLD_CONDA_ENV:-/Users/oswaldkid/miniforge3/envs/esmfold}/bin"
PORT="${ESMFOLD_PORT:-8004}"

export PATH="$CONDA_ENV_BIN:$PATH"

echo "Starting ESMFold server on port $PORT"
cd "$(dirname "$0")"
exec "$CONDA_ENV_BIN/uvicorn" server:app --host 127.0.0.1 --port "$PORT"
