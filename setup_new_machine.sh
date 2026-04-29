#!/usr/bin/env bash
# Run this once on a fresh Mac to set up the Protein Design Platform.
set -e

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "Setting up from: $REPO_DIR"

# ── Check prerequisites ────────────────────────────────────────────────────────
check() { command -v "$1" &>/dev/null || { echo "✗ $1 not found — install it first"; exit 1; }; echo "✓ $1"; }
check node
check npm
check git

# Find a Python >= 3.10
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" &>/dev/null; then
    VER=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
    MAJOR=$(echo "$VER" | cut -d. -f1)
    MINOR=$(echo "$VER" | cut -d. -f2)
    if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
      PYTHON="$candidate"
      break
    fi
  fi
done

if [ -z "$PYTHON" ]; then
  echo ""
  echo "✗ Python 3.10 or newer is required but not found."
  echo ""
  echo "  Install it with Homebrew:"
  echo "    brew install python@3.12"
  echo ""
  echo "  Then re-run this script."
  exit 1
fi

echo "✓ $PYTHON ($("$PYTHON" --version))"
NODE_VER=$(node --version)
echo "✓ node $NODE_VER"

# ── Backend venv ──────────────────────────────────────────────────────────────
echo ""
echo "Setting up backend..."
cd "$REPO_DIR/backend"
if [ ! -d ".venv" ]; then
  "$PYTHON" -m venv .venv
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
