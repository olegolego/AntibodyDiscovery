#!/usr/bin/env bash
# Set up the Python venv for the GROMACS tool.
# Heavy binaries (gmx, gmx_MMPBSA, cpptraj) are NOT installed here —
# they must already be on PATH (conda mmpbsa env). See SETUP.md.
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -m venv "$TOOL_DIR/.venv"
"$TOOL_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel certifi

CERT_PATH=$("$TOOL_DIR/.venv/bin/python" -c "import certifi; print(certifi.where())" 2>/dev/null || echo "")
if [ -n "$CERT_PATH" ]; then
    SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
        "$TOOL_DIR/.venv/bin/pip" install -q numpy matplotlib
    SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
        "$TOOL_DIR/.venv/bin/pip" install -q MDAnalysis || \
        echo "MDAnalysis install failed (optional, used for RMSD analysis)"
else
    "$TOOL_DIR/.venv/bin/pip" install -q numpy matplotlib
    "$TOOL_DIR/.venv/bin/pip" install -q MDAnalysis || \
        echo "MDAnalysis install failed (optional)"
fi

echo ""
echo "✓ GROMACS tool Python venv ready at $TOOL_DIR/.venv"
echo ""
echo "⚠  System dependencies required on PATH:"
echo "   gmx         — GROMACS 2020+ (conda install -c conda-forge gromacs)"
echo "   gmx_MMPBSA  — (conda install -c conda-forge gmx_mmpbsa)"
echo "   cpptraj     — AmberTools (conda install -c conda-forge ambertools)"
echo ""
echo "Typical activation: conda activate mmpbsa"
