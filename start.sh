#!/usr/bin/env bash
# Start all servers: backend, frontend, and AbMAP.
# Binds to 0.0.0.0 so the app is reachable from other machines on the network.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Detect local IP (first non-loopback IPv4) ─────────────────────────────────
HOST_IP=$(ipconfig getifaddr en0 2>/dev/null \
  || ip route get 1 2>/dev/null | awk '{print $7; exit}' \
  || echo "localhost")

# ── Kill any existing processes on known ports ────────────────────────────────
echo "Stopping existing processes..."
lsof -ti :8000 :5173 :8005 | xargs kill -9 2>/dev/null || true

# ── AbMAP ─────────────────────────────────────────────────────────────────────
echo "Starting AbMAP server (port 8005)..."
cd "$REPO_DIR/tools/abmap"
bash start.sh > /tmp/abmap.log 2>&1 &
ABMAP_PID=$!

# ── Backend ───────────────────────────────────────────────────────────────────
echo "Starting backend (port 8000)..."
cd "$REPO_DIR/backend"
source .venv/bin/activate
# --host 0.0.0.0 makes it reachable from other machines
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "Starting frontend (port 5173)..."
cd "$REPO_DIR/frontend"
# --host exposes vite on the network; VITE_API_HOST tells the app where the backend is
VITE_API_HOST="http://$HOST_IP:8000" npm run dev -- --host 0.0.0.0 > /tmp/frontend.log 2>&1 &
FRONTEND_PID=$!

# ── Wait for all to be ready ──────────────────────────────────────────────────
echo ""
echo "Waiting for servers to start..."

for i in $(seq 1 20); do
  sleep 1
  BACKEND_OK=0; FRONTEND_OK=0; ABMAP_OK=0
  curl -sf http://localhost:8000/api/tools > /dev/null 2>&1 && BACKEND_OK=1
  curl -sf http://localhost:5173           > /dev/null 2>&1 && FRONTEND_OK=1
  curl -sf http://localhost:8005/health    > /dev/null 2>&1 && ABMAP_OK=1
  if [ $BACKEND_OK -eq 1 ] && [ $FRONTEND_OK -eq 1 ] && [ $ABMAP_OK -eq 1 ]; then
    break
  fi
done

echo ""
echo "═══════════════════════════════════════════════════"
printf "  Backend   http://%-22s %s\n" "$HOST_IP:8000" "$([ $BACKEND_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/backend.log')"
printf "  Frontend  http://%-22s %s\n" "$HOST_IP:5173" "$([ $FRONTEND_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/frontend.log')"
printf "  AbMAP     http://%-22s %s\n" "$HOST_IP:8005" "$([ $ABMAP_OK -eq 1 ] && echo '✓' || echo '✗ check /tmp/abmap.log')"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Open on this machine:      http://localhost:5173"
echo "  Open from other machines:  http://$HOST_IP:5173"
echo ""
echo "PIDs: backend=$BACKEND_PID  frontend=$FRONTEND_PID  abmap=$ABMAP_PID"
echo "Logs: /tmp/backend.log  /tmp/frontend.log  /tmp/abmap.log"
echo ""
echo "Press Ctrl+C to stop all servers."

# ── Keep script alive; kill children on exit ──────────────────────────────────
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID $ABMAP_PID 2>/dev/null; exit 0" INT TERM

wait
