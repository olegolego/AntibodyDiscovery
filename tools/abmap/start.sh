#!/usr/bin/env bash
# Start the AbMAP HTTP server.
# Paths and port come from environment variables set by the root start.sh
# (which sources config.env). Fallbacks are provided for standalone use.
set -e

CONDA_ENV_BIN="${ABMAP_CONDA_ENV:-/Users/oswaldkid/miniforge3/envs/abmap}/bin"
ABMAP_HOME="${ABMAP_HOME:-/Users/oswaldkid/abmap}"
PORT="${ABMAP_PORT:-8005}"

export PATH="$CONDA_ENV_BIN:$PATH"
export ABMAP_HOME="$ABMAP_HOME"
export KMP_DUPLICATE_LIB_OK=TRUE

echo "Starting AbMAP server on port $PORT (ABMAP_HOME=$ABMAP_HOME)"
exec "$CONDA_ENV_BIN/uvicorn" server:app --host 127.0.0.1 --port "$PORT"
