#!/usr/bin/env bash
# Start the AbMAP HTTP server.
# ANARCI must be on PATH — it lives inside the myenv conda environment.
set -e

CONDA_ENV_BIN="/Users/olegpresnyakov/opt/anaconda3/envs/myenv/bin"
ABMAP_HOME="${ABMAP_HOME:-/Users/olegpresnyakov/abmap}"
PORT="${ABMAP_PORT:-8005}"

export PATH="$CONDA_ENV_BIN:$PATH"
export ABMAP_HOME="$ABMAP_HOME"

echo "Starting AbMAP server on port $PORT (ABMAP_HOME=$ABMAP_HOME)"
exec "$CONDA_ENV_BIN/uvicorn" server:app --host 0.0.0.0 --port "$PORT"
