#!/usr/bin/env bash
# Start all servers. Frontend binds to 0.0.0.0 so other machines can connect.
# Backend and AbMAP are localhost-only; all external traffic goes through the Vite proxy.
set -e

# Ensure Homebrew and Claude CLI are in PATH (needed when launched over SSH)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$HOME/.local/bin:$PATH"

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Load shared config ────────────────────────────────────────────────────────
# shellcheck source=config.env
source "$REPO_DIR/config.env"

# ── Detect local IP (first non-loopback IPv4) ─────────────────────────────────
HOST_IP=$(
  for iface in en0 en1 en2 en3 en4 en5; do
    ip=$(ipconfig getifaddr "$iface" 2>/dev/null)
    [ -n "$ip" ] && echo "$ip" && break
  done
)
[ -z "$HOST_IP" ] && HOST_IP=$(ifconfig | awk '/inet / && !/127\.0\.0\.1/{print $2; exit}')
HOST_IP=${HOST_IP:-localhost}

# Allow the frontend origin from both localhost and the LAN IP.
export CORS_ALLOWED_ORIGINS="http://localhost:${FRONTEND_PORT},http://${HOST_IP}:${FRONTEND_PORT}"

# Export AbMAP settings so tools/abmap/start.sh picks them up from the environment.
export ABMAP_CONDA_ENV
export ABMAP_HOME
export ABMAP_PORT
export BIOPHI_CONDA_ENV

# Export ProteinMPNN settings so tools/proteinmpnn/start.sh picks them up.
export PROTEINMPNN_CONDA_ENV
export PROTEINMPNN_HOME
export PROTEINMPNN_PORT

# Export ESMFold settings so tools/esmfold/start.sh picks them up.
export ESMFOLD_CONDA_ENV
export ESMFOLD_PORT

# Export CHEAP Embedding settings so tools/cheap_embedding/start.sh picks them up.
export CHEAP_CONDA_ENV
export CHEAP_EMBEDDING_PORT
export CHEAP_EMBEDDING_URL

# Export tool URLs so the backend picks them up from the environment.
export ABMAP_URL ALPHAFOLD_URL RFDIFFUSION_URL PROTEINMPNN_URL ESMFOLD_URL CHEAP_EMBEDDING_URL BOLTZ2_URL

# ── Kill any existing processes on known ports ────────────────────────────────
echo "Stopping existing processes..."
lsof -ti:${BACKEND_PORT}      | xargs kill -9 2>/dev/null || true
lsof -ti:${FRONTEND_PORT}     | xargs kill -9 2>/dev/null || true
lsof -ti:${ABMAP_PORT}        | xargs kill -9 2>/dev/null || true
lsof -ti:${PROTEINMPNN_PORT}  | xargs kill -9 2>/dev/null || true
lsof -ti:${ESMFOLD_PORT}          | xargs kill -9 2>/dev/null || true
lsof -ti:${CHEAP_EMBEDDING_PORT}  | xargs kill -9 2>/dev/null || true
lsof -ti:${BOLTZ2_PORT}           | xargs kill -9 2>/dev/null || true

# ── Docker tool services (optional — ESMFold / others) ───────────────────────
if [ "${START_DOCKER_TOOLS:-0}" = "1" ]; then
  if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    echo "Starting additional Docker tool services (ESMFold)..."
    docker compose -f "$REPO_DIR/docker-compose.yml" up -d esmfold 2>&1 | tail -4
  else
    echo "WARNING: START_DOCKER_TOOLS=1 but docker not running — skipping"
  fi
fi

# ── ESMFold ───────────────────────────────────────────────────────────────────
echo "Starting ESMFold server (port ${ESMFOLD_PORT})..."
cd "$REPO_DIR/tools/esmfold"
bash start.sh > /tmp/esmfold.log 2>&1 &
ESMFOLD_PID=$!

# ── ProteinMPNN ───────────────────────────────────────────────────────────────
echo "Starting ProteinMPNN server (port ${PROTEINMPNN_PORT})..."
cd "$REPO_DIR/tools/proteinmpnn"
bash start.sh > /tmp/proteinmpnn.log 2>&1 &
PROTEINMPNN_PID=$!

# ── CHEAP Embedding ───────────────────────────────────────────────────────────
echo "Starting CHEAP Embedding server (port ${CHEAP_EMBEDDING_PORT})..."
cd "$REPO_DIR/tools/cheap_embedding"
bash start.sh > /tmp/cheap_embedding.log 2>&1 &
CHEAP_PID=$!

# ── AbMAP ─────────────────────────────────────────────────────────────────────
echo "Starting AbMAP server (port ${ABMAP_PORT})..."
cd "$REPO_DIR/tools/abmap"
bash start.sh > /tmp/abmap.log 2>&1 &
ABMAP_PID=$!

# ── Boltz2 ───────────────────────────────────────────────────────────────────
BOLTZ2_PID=""
if [ -f "$REPO_DIR/tools/boltz2/.venv/bin/uvicorn" ]; then
  echo "Starting Boltz2 server (port ${BOLTZ2_PORT})..."
  cd "$REPO_DIR/tools/boltz2"
  .venv/bin/uvicorn server:app --host 127.0.0.1 --port "${BOLTZ2_PORT}" > /tmp/boltz2.log 2>&1 &
  BOLTZ2_PID=$!
else
  echo "Boltz2 venv not found — skipping (run: cd tools/boltz2 && python3.12 -m venv .venv && .venv/bin/pip install boltz uvicorn fastapi pydantic)"
fi

# ── Backend ───────────────────────────────────────────────────────────────────
echo "Starting backend (port ${BACKEND_PORT})..."
cd "$REPO_DIR/backend"
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" > /tmp/backend.log 2>&1 &
BACKEND_PID=$!

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "Starting frontend (port ${FRONTEND_PORT})..."
cd "$REPO_DIR/frontend"
VITE_API_HOST="http://localhost:${BACKEND_PORT}" npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}" > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!

# ── Wait for all to be ready ──────────────────────────────────────────────────
echo ""
echo "Waiting for servers to start..."

for i in $(seq 1 30); do
  sleep 1
  BACKEND_OK=0; FRONTEND_OK=0; ABMAP_OK=0; PROTEINMPNN_OK=0; ESMFOLD_OK=0; CHEAP_OK=0
  curl -sfL "http://localhost:${BACKEND_PORT}/api/tools/"        > /dev/null 2>&1 && BACKEND_OK=1
  curl -sf  "http://localhost:${FRONTEND_PORT}"                  > /dev/null 2>&1 && FRONTEND_OK=1
  curl -sf  "http://localhost:${ABMAP_PORT}/health"              > /dev/null 2>&1 && ABMAP_OK=1
  curl -sf  "http://localhost:${PROTEINMPNN_PORT}/health"        > /dev/null 2>&1 && PROTEINMPNN_OK=1
  curl -sf  "http://localhost:${ESMFOLD_PORT}/health"            > /dev/null 2>&1 && ESMFOLD_OK=1
  curl -sf  "http://localhost:${CHEAP_EMBEDDING_PORT}/health"    > /dev/null 2>&1 && CHEAP_OK=1
  if [ $BACKEND_OK -eq 1 ] && [ $FRONTEND_OK -eq 1 ] && [ $ABMAP_OK -eq 1 ] && [ $PROTEINMPNN_OK -eq 1 ] && [ $ESMFOLD_OK -eq 1 ] && [ $CHEAP_OK -eq 1 ]; then
    break
  fi
done

echo ""
echo "═══════════════════════════════════════════════════"
printf "  Backend      http://%-22s %s\n" "localhost:${BACKEND_PORT} (internal)" "$([ $BACKEND_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/backend.log')"
printf "  Frontend     http://%-22s %s\n" "${HOST_IP}:${FRONTEND_PORT}" "$([ $FRONTEND_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/frontend.log')"
printf "  AbMAP        http://%-22s %s\n" "localhost:${ABMAP_PORT} (internal)" "$([ $ABMAP_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/abmap.log')"
printf "  ProteinMPNN  http://%-22s %s\n" "localhost:${PROTEINMPNN_PORT} (internal)" "$([ $PROTEINMPNN_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/proteinmpnn.log')"
printf "  ESMFold      http://%-22s %s\n" "localhost:${ESMFOLD_PORT} (internal)" "$([ $ESMFOLD_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/esmfold.log')"
printf "  CHEAP Embed  http://%-22s %s\n" "localhost:${CHEAP_EMBEDDING_PORT} (internal)" "$([ $CHEAP_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/cheap_embedding.log')"
BOLTZ2_OK=0; curl -sf "http://localhost:${BOLTZ2_PORT}/health" > /dev/null 2>&1 && BOLTZ2_OK=1
printf "  Boltz2       http://%-22s %s\n" "localhost:${BOLTZ2_PORT} (internal)" "$([ $BOLTZ2_OK -eq 1 ] && echo '✓' || ([ -n "$BOLTZ2_PID" ] && echo '✗ check /tmp/boltz2.log' || echo '— not installed (see tools/boltz2/SETUP.md)'))"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Open from this machine:    http://localhost:${FRONTEND_PORT}"
echo "  Open from other machines:  http://${HOST_IP}:${FRONTEND_PORT}"
echo ""
echo "PIDs: backend=$BACKEND_PID  frontend=$FRONTEND_PID  abmap=$ABMAP_PID  proteinmpnn=$PROTEINMPNN_PID  esmfold=$ESMFOLD_PID  cheap=$CHEAP_PID  boltz2=${BOLTZ2_PID:-n/a}"
echo "Logs: /tmp/backend.log  /tmp/frontend.log  /tmp/abmap.log  /tmp/proteinmpnn.log  /tmp/esmfold.log  /tmp/cheap_embedding.log  /tmp/boltz2.log"
echo ""
echo "Press Ctrl+C to stop all servers."

# ── Keep script alive; kill children on exit ──────────────────────────────────
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID $ABMAP_PID $PROTEINMPNN_PID $ESMFOLD_PID $CHEAP_PID ${BOLTZ2_PID} 2>/dev/null; exit 0" INT TERM

wait
