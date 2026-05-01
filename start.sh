#!/usr/bin/env bash
# Start all servers. Frontend binds to 0.0.0.0 so other machines can connect.
# Backend and AbMAP are localhost-only; all external traffic goes through the Vite proxy.
set -e

# Ensure Homebrew tools are in PATH (needed when launched over SSH)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"

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
# The backend process inherits this; pydantic-settings reads it as CORS_ALLOWED_ORIGINS.
export CORS_ALLOWED_ORIGINS="http://localhost:${FRONTEND_PORT},http://${HOST_IP}:${FRONTEND_PORT}"

# Export AbMAP settings so tools/abmap/start.sh picks them up from the environment.
export ABMAP_CONDA_ENV
export ABMAP_HOME
export ABMAP_PORT
export BIOPHI_CONDA_ENV

# Export tool URLs so the backend picks them up from the environment.
export ABMAP_URL ALPHAFOLD_URL RFDIFFUSION_URL PROTEINMPNN_URL ESMFOLD_URL

# ── Docker tool services (optional) ──────────────────────────────────────────
if [ "${START_DOCKER_TOOLS:-0}" = "1" ]; then
  if command -v docker &>/dev/null; then
    echo "Starting Docker tool services (ProteinMPNN, ESMFold)..."
    docker compose -f "$REPO_DIR/docker-compose.yml" up -d 2>&1 | tail -4
  else
    echo "WARNING: START_DOCKER_TOOLS=1 but docker not found — skipping"
  fi
fi

# ── Kill any existing processes on known ports ────────────────────────────────
echo "Stopping existing processes..."
lsof -ti:${BACKEND_PORT}  | xargs kill -9 2>/dev/null || true
lsof -ti:${FRONTEND_PORT} | xargs kill -9 2>/dev/null || true
lsof -ti:${ABMAP_PORT}    | xargs kill -9 2>/dev/null || true

# ── AbMAP ─────────────────────────────────────────────────────────────────────
echo "Starting AbMAP server (port ${ABMAP_PORT})..."
cd "$REPO_DIR/tools/abmap"
bash start.sh > /tmp/abmap.log 2>&1 &
ABMAP_PID=$!

# ── Backend ───────────────────────────────────────────────────────────────────
echo "Starting backend (port ${BACKEND_PORT})..."
cd "$REPO_DIR/backend"
source .venv/bin/activate
# Bind to localhost only — all external traffic goes through the Vite proxy
uvicorn app.main:app --reload --host 127.0.0.1 --port "${BACKEND_PORT}" > /tmp/backend.log 2>&1 &
BACKEND_PID=$!

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "Starting frontend (port ${FRONTEND_PORT})..."
cd "$REPO_DIR/frontend"
# VITE_API_HOST is used by vite.config.ts for the proxy target (server-side, always localhost)
VITE_API_HOST="http://localhost:${BACKEND_PORT}" npm run dev -- --host 0.0.0.0 --port "${FRONTEND_PORT}" > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!

# ── Wait for all to be ready ──────────────────────────────────────────────────
echo ""
echo "Waiting for servers to start..."

for i in $(seq 1 20); do
  sleep 1
  BACKEND_OK=0; FRONTEND_OK=0; ABMAP_OK=0
  curl -sfL "http://localhost:${BACKEND_PORT}/api/tools/"  > /dev/null 2>&1 && BACKEND_OK=1
  curl -sf  "http://localhost:${FRONTEND_PORT}"            > /dev/null 2>&1 && FRONTEND_OK=1
  curl -sf  "http://localhost:${ABMAP_PORT}/health"        > /dev/null 2>&1 && ABMAP_OK=1
  if [ $BACKEND_OK -eq 1 ] && [ $FRONTEND_OK -eq 1 ] && [ $ABMAP_OK -eq 1 ]; then
    break
  fi
done

echo ""
echo "═══════════════════════════════════════════════════"
printf "  Backend   http://%-22s %s\n" "localhost:${BACKEND_PORT} (internal)" "$([ $BACKEND_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/backend.log')"
printf "  Frontend  http://%-22s %s\n" "${HOST_IP}:${FRONTEND_PORT}" "$([ $FRONTEND_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/frontend.log')"
printf "  AbMAP     http://%-22s %s\n" "localhost:${ABMAP_PORT} (internal)" "$([ $ABMAP_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/abmap.log')"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Open from this machine:    http://localhost:${FRONTEND_PORT}"
echo "  Open from other machines:  http://${HOST_IP}:${FRONTEND_PORT}"
echo ""
echo "PIDs: backend=$BACKEND_PID  frontend=$FRONTEND_PID  abmap=$ABMAP_PID"
echo "Logs: /tmp/backend.log  /tmp/frontend.log  /tmp/abmap.log"
echo ""
echo "Press Ctrl+C to stop all servers."

# ── Keep script alive; kill children on exit ──────────────────────────────────
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID $ABMAP_PID 2>/dev/null; exit 0" INT TERM

wait
