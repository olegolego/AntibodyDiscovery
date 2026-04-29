#!/usr/bin/env bash
# Start all servers: backend, frontend, and AbMAP.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

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
uvicorn app.main:app --reload --port 8000 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!

# ── Frontend ──────────────────────────────────────────────────────────────────
echo "Starting frontend (port 5173)..."
cd "$REPO_DIR/frontend"
npm run dev > /tmp/frontend.log 2>&1 &
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
echo "═══════════════════════════════════════"
printf "  Backend   http://localhost:8000  %s\n" "$([ $BACKEND_OK -eq 1 ] && echo '✓' || echo '✗ (check /tmp/backend.log)')"
printf "  Frontend  http://localhost:5173  %s\n" "$([ $FRONTEND_OK -eq 1 ] && echo '✓' || echo '✗ (check /tmp/frontend.log)')"
printf "  AbMAP     http://localhost:8005  %s\n" "$([ $ABMAP_OK -eq 1 ] && echo '✓' || echo '✗ (check /tmp/abmap.log)')"
echo "═══════════════════════════════════════"
echo ""
echo "PIDs: backend=$BACKEND_PID  frontend=$FRONTEND_PID  abmap=$ABMAP_PID"
echo "Logs: /tmp/backend.log  /tmp/frontend.log  /tmp/abmap.log"
echo ""
echo "Press Ctrl+C to stop all servers."

# ── Keep script alive; kill children on exit ──────────────────────────────────
trap "echo ''; echo 'Stopping...'; kill $BACKEND_PID $FRONTEND_PID $ABMAP_PID 2>/dev/null; exit 0" INT TERM

wait
