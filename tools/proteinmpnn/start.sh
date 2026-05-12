#!/usr/bin/env bash
# Start the ProteinMPNN HTTP server.
# Paths and port come from environment variables set by the root start.sh
# (which sources config.env). Fallbacks are provided for standalone use.
set -e

CONDA_ENV_BIN="${PROTEINMPNN_CONDA_ENV:-/Users/oswaldkid/miniforge3/envs/superwater}/bin"
PROTEINMPNN_HOME="${PROTEINMPNN_HOME:-/Users/oswaldkid/ProteinMPNN}"
PORT="${PROTEINMPNN_PORT:-8003}"

export PATH="$CONDA_ENV_BIN:$PATH"
export PROTEINMPNN_REPO="$PROTEINMPNN_HOME"
export PROTEINMPNN_PYTHON="$CONDA_ENV_BIN/python"

echo "Starting ProteinMPNN server on port $PORT (repo=$PROTEINMPNN_HOME)"
cd "$(dirname "$0")"
exec "$CONDA_ENV_BIN/uvicorn" server:app --host 127.0.0.1 --port "$PORT"
