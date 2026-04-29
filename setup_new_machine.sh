#!/usr/bin/env bash
# Run this once on a fresh Mac to set up the Protein Design Platform.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Setting up from: $REPO_DIR"

# ── Check prerequisites ────────────────────────────────────────────────────────
check() { command -v "$1" &>/dev/null || { echo "✗ $1 not found — install it first"; exit 1; }; echo "✓ $1"; }
check python3
check node
check npm
check git

PYTHON_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python $PYTHON_VER"
NODE_VER=$(node --version)
echo "  Node $NODE_VER"

# ── Backend venv ──────────────────────────────────────────────────────────────
echo ""
echo "Setting up backend..."
cd "$REPO_DIR/backend"
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e ".[dev]" -q
echo "✓ Backend venv ready"

# ── Copy .env if not present ──────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  cp .env.example .env 2>/dev/null || true
  echo "✓ Created backend/.env — edit tool URLs if needed"
else
  echo "✓ backend/.env already exists"
fi

# ── Frontend deps ─────────────────────────────────────────────────────────────
echo ""
echo "Setting up frontend..."
cd "$REPO_DIR/frontend"
npm install --legacy-peer-deps -q
echo "✓ Frontend dependencies installed"

# ── Tool venvs ────────────────────────────────────────────────────────────────
echo ""
echo "Setting up tool environments..."
for tool in immunebuilder ablang equidock haddock3; do
  SETUP="$REPO_DIR/tools/$tool/setup.sh"
  if [ -f "$SETUP" ]; then
    echo "  Running $tool/setup.sh..."
    bash "$SETUP" || echo "  ⚠ $tool setup had errors — check manually"
  fi
done

# ── macOS firewall reminder ───────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Setup complete!"
echo ""
echo "  To allow other Macs to connect, make sure macOS firewall"
echo "  is not blocking ports 5173 and 8000:"
echo "    System Settings → Network → Firewall → Options"
echo "    (or just turn off the firewall on this machine)"
echo ""
echo "  To start all servers:"
echo "    bash start.sh"
echo ""
echo "  Other machines on the network open:"
echo "    http://<this-mac-ip>:5173"
echo "    (start.sh will print the exact URL)"
echo "═══════════════════════════════════════════════════════════"
