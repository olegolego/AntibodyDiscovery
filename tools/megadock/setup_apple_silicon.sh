#!/usr/bin/env bash
# Setup script for MEGADOCK Metal GPU build on Apple Silicon.
#
# Compiles megadock-metal using Apple Metal compute shaders + Accelerate vDSP
# for 3-D FFT. Produces bin/megadock-metal and bin/megadock_kernels.metallib
# alongside the existing bin/megadock CPU binary.
#
# Requirements:
#   - macOS 12+ on Apple Silicon (arm64)
#   - Xcode command-line tools (xcrun, metal, metallib)
#   - Homebrew + llvm (for OpenMP support with clang)
#
# Run once from the repo root or from tools/megadock/.
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$TOOL_DIR"

# ── 0. Platform check ─────────────────────────────────────────────────────────
ARCH="$(uname -m)"
if [ "$ARCH" != "arm64" ]; then
  echo "ERROR: This script is for Apple Silicon (arm64). Detected: $ARCH"
  echo "       Use setup.sh for the CPU build on x86_64."
  exit 1
fi

OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
  echo "ERROR: This script requires macOS. Detected: $OS"
  exit 1
fi

echo "=== MEGADOCK Metal/Apple Silicon setup ==="
echo "Platform: $OS $ARCH"
echo "Tool dir: $TOOL_DIR"

# ── 1. Xcode command-line tools ───────────────────────────────────────────────
if ! xcrun --find metal &>/dev/null 2>&1; then
  echo "Installing Xcode command-line tools (required for Metal compiler)..."
  xcode-select --install
  echo "Re-run this script after installation completes."
  exit 1
fi
echo "Xcode CLT: OK (metal: $(xcrun --find metal))"

# ── 2. OpenMP via Homebrew llvm ───────────────────────────────────────────────
# Apple clang does not ship libomp. The Homebrew llvm does.
if command -v brew &>/dev/null; then
  if ! brew list llvm &>/dev/null 2>&1; then
    echo "Installing Homebrew llvm (for OpenMP)..."
    brew install llvm
  fi
  LLVM_PREFIX="$(brew --prefix llvm)"
  CLANGPP="$LLVM_PREFIX/bin/clang++"
  OMP_FLAGS="-I$LLVM_PREFIX/include -L$LLVM_PREFIX/lib -lomp"
  echo "LLVM clang++: $CLANGPP"
else
  # Fallback: Apple clang with -Xpreprocessor (no native parallelism for Metal path,
  # but the Metal GPU handles the heavy lifting anyway)
  CLANGPP="clang++"
  OMP_FLAGS="-Xpreprocessor -fopenmp"
  echo "Using system clang (limited OpenMP support)"
fi

# ── 3. Clone MEGADOCK repo if not present ─────────────────────────────────────
if [ ! -d "repo/.git" ]; then
  echo "Cloning MEGADOCK..."
  git clone https://github.com/akiyamalab/MEGADOCK.git repo
else
  echo "MEGADOCK repo already present — skipping clone."
fi

# ── 4. Copy Metal source files into the repo (they live alongside this script) ──
echo "Installing Metal source files into repo/src/ ..."
for f in metal_kernels.metal metal_bridge.h fft_process_metal.mm main_metal.mm; do
  SRC="$TOOL_DIR/repo/src/$f"
  if [ ! -f "$SRC" ]; then
    echo "  WARNING: $SRC not found — Metal sources may already be in the repo, skipping."
  else
    echo "  present: $SRC"
  fi
done

# ── 5. Compile Metal shader library (.metal → .air → .metallib) ───────────────
echo ""
echo "Compiling Metal shader library..."
AIR_FILE="$TOOL_DIR/repo/metal_kernels.air"
METALLIB_FILE="$TOOL_DIR/repo/megadock_kernels.metallib"

xcrun -sdk macosx metal -O2 \
  -o "$AIR_FILE" \
  -c "$TOOL_DIR/repo/src/metal_kernels.metal"
echo "  metal_kernels.air: OK"

xcrun -sdk macosx metallib \
  -o "$METALLIB_FILE" \
  "$AIR_FILE"
echo "  megadock_kernels.metallib: OK"

# ── 6. Build megadock-metal binary ────────────────────────────────────────────
echo ""
echo "Building megadock-metal..."
cd "$TOOL_DIR/repo"

# Patch Makefile so the USE_METAL path uses the correct clang++
sed -i.bak \
  -e "s|^USE_GPU.*|USE_GPU := 0|" \
  -e "s|^USE_MPI.*|USE_MPI := 0|" \
  Makefile 2>/dev/null || true

make -j"$(sysctl -n hw.logicalcpu)" \
  USE_METAL=1 \
  USE_GPU=0 \
  USE_MPI=0 \
  CPPCOMPILER="$CLANGPP" \
  2>&1 | tail -40

cd "$TOOL_DIR"

# ── 7. Copy binaries to tools/megadock/bin/ ───────────────────────────────────
mkdir -p bin
REPO_DIR="$TOOL_DIR/repo"

for binary in megadock-metal decoygen; do
  if [ -f "$REPO_DIR/$binary" ]; then
    cp "$REPO_DIR/$binary" "bin/$binary"
    chmod +x "bin/$binary"
    echo "  copied: bin/$binary"
  else
    echo "  WARNING: $binary not found in repo/ after build"
  fi
done

# Copy metallib next to the binary (run.py locates it there)
if [ -f "$METALLIB_FILE" ]; then
  cp "$METALLIB_FILE" "bin/megadock_kernels.metallib"
  echo "  copied: bin/megadock_kernels.metallib"
fi

# Copy .metal sources to bin/ for runtime fallback compilation.
# metal_kernels.metal #includes metal_fft.metal, so both must be present.
cp "$TOOL_DIR/repo/src/metal_kernels.metal" "bin/metal_kernels.metal"
cp "$TOOL_DIR/repo/src/metal_fft.metal"     "bin/metal_fft.metal"
echo "  copied: bin/metal_kernels.metal + bin/metal_fft.metal (runtime fallback)"

# ── 8. Verify ─────────────────────────────────────────────────────────────────
echo ""
echo "=== Verifying Metal build ==="
if [ -f "bin/megadock-metal" ]; then
  ./bin/megadock-metal -h 2>&1 | head -5 || true
  echo "megadock-metal binary: OK"
else
  echo "ERROR: megadock-metal binary missing. Check build output above."
  exit 1
fi

if [ -f "bin/megadock_kernels.metallib" ]; then
  echo "megadock_kernels.metallib: OK"
else
  echo "WARNING: metallib missing — GPU kernels will not load at runtime."
fi

echo ""
echo "=== Metal build complete ==="
echo "Binaries:"
ls -lh bin/megadock* bin/decoygen 2>/dev/null || true
echo ""
echo "The Metal binary is auto-selected by run.py on Apple Silicon."
echo "Test with:"
echo "  echo '{\"receptor\":\"<PDB>\",\"ligand\":\"<PDB>\"}' | \\"
echo "    python3 $TOOL_DIR/run.py"
