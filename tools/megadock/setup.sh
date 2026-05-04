#!/usr/bin/env bash
# Setup script for MEGADOCK (C++ FFT-based protein-protein docking).
# Installs FFTW3 (via Homebrew on macOS), clones the repo, compiles CPU binary.
# Run once from the repo root or from tools/megadock/.
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TOOL_DIR"

echo "=== MEGADOCK setup ==="
echo "Tool dir: $TOOL_DIR"

# ── 1. Install FFTW3 ───────────────────────────────────────────────────────────
if command -v brew &>/dev/null; then
  if brew list fftw &>/dev/null 2>&1; then
    echo "FFTW3 already installed."
  else
    echo "Installing FFTW3 via Homebrew..."
    brew install fftw
  fi
  FFTW_PATH="$(brew --prefix fftw)"
else
  # Linux fallback
  if [ -d "/usr/include/fftw3.h" ] || pkg-config --exists fftw3f 2>/dev/null; then
    echo "FFTW3 found on system."
    FFTW_PATH="/usr"
  else
    echo "ERROR: FFTW3 not found. Install with:"
    echo "  macOS:  brew install fftw"
    echo "  Ubuntu: apt-get install libfftw3-dev"
    exit 1
  fi
fi
echo "FFTW3 path: $FFTW_PATH"

# ── 2. Find C++ compiler with OpenMP support ───────────────────────────────────
if command -v brew &>/dev/null; then
  # Prefer Homebrew GCC (has native OpenMP) over Apple clang (needs libomp flags)
  GCC_BIN="$(ls /opt/homebrew/bin/g++-* 2>/dev/null | sort -V | tail -1 \
             || ls /usr/local/bin/g++-* 2>/dev/null | sort -V | tail -1 \
             || echo "")"
  if [ -n "$GCC_BIN" ]; then
    CPPCOMPILER="$GCC_BIN"
    echo "Using Homebrew GCC: $CPPCOMPILER"
  else
    echo "Homebrew GCC not found — installing..."
    brew install gcc
    GCC_BIN="$(ls /opt/homebrew/bin/g++-* 2>/dev/null | sort -V | tail -1)"
    CPPCOMPILER="$GCC_BIN"
    echo "Using: $CPPCOMPILER"
  fi
else
  CPPCOMPILER="g++"
fi

# ── 3. Clone MEGADOCK ──────────────────────────────────────────────────────────
if [ ! -d "repo/.git" ]; then
  echo "Cloning MEGADOCK..."
  git clone https://github.com/akiyamalab/MEGADOCK.git repo
else
  echo "MEGADOCK repo already present — skipping clone."
fi

# ── 4. Compile (CPU-only, no MPI, with OpenMP) ────────────────────────────────
echo "Compiling MEGADOCK (CPU, no MPI, no GPU)..."
cd repo

# Patch Makefile for macOS paths and disable GPU/MPI
sed -i.bak \
  -e "s|^USE_GPU.*|USE_GPU := 0|" \
  -e "s|^USE_MPI.*|USE_MPI := 0|" \
  -e "s|^FFTW_INSTALL_PATH.*|FFTW_INSTALL_PATH := $FFTW_PATH|" \
  -e "s|^CPPCOMPILER.*|CPPCOMPILER := $CPPCOMPILER|" \
  Makefile 2>/dev/null || true

# Build (overrides as fallback in case sed didn't match)
make -j4 \
  USE_GPU=0 \
  USE_MPI=0 \
  FFTW_INSTALL_PATH="$FFTW_PATH" \
  CPPCOMPILER="$CPPCOMPILER" \
  2>&1 | tail -30

cd "$TOOL_DIR"

# ── 5. Copy binaries to tools/megadock/bin/ ───────────────────────────────────
mkdir -p bin
BIN_SRC="$TOOL_DIR/repo"

for binary in megadock decoygen; do
  if [ -f "$BIN_SRC/$binary" ]; then
    cp "$BIN_SRC/$binary" "bin/$binary"
    chmod +x "bin/$binary"
    echo "  copied: bin/$binary"
  else
    echo "  WARNING: $binary not found in repo/ after build"
  fi
done

# ── 6. Create .venv with matplotlib for docking visualization ─────────────────
if [ ! -d ".venv/bin" ]; then
  echo "Creating Python venv..."
  python3 -m venv .venv
fi
echo "Installing visualization deps (matplotlib, numpy)..."
.venv/bin/pip install --quiet matplotlib numpy

# ── 7. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Verifying build ==="
if [ -f "bin/megadock" ]; then
  ./bin/megadock -h 2>&1 | head -5 || true
  echo "megadock binary: OK"
else
  echo "ERROR: megadock binary missing. Check build output above."
  exit 1
fi

if [ -f "bin/decoygen" ]; then
  echo "decoygen binary: OK"
else
  echo "WARNING: decoygen binary missing. Complex generation will fail."
fi

echo ""
echo "=== Setup complete ==="
echo "Binaries: $TOOL_DIR/bin/"
echo ""
echo "Test:"
echo "  echo '{\"receptor\":\"<PDB>\",\"ligand\":\"<PDB>\"}' | \\"
echo "    .venv/bin/python3 $TOOL_DIR/run.py"
