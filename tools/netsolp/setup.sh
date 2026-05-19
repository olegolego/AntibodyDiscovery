#!/usr/bin/env bash
# NetSolP setup script.
#
# Default mode: uses biopython (already in the abmap env) with a
# physicochemical regression model — no downloads required.
#
# Optional: download the full NetSolP ONNX models for ML-based prediction.
# WARNING: the DTU archive is ~5.6 GB. Only run with --download-models if
# you need higher accuracy and have the bandwidth.
set -euo pipefail

TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
ABMAP_PYTHON="/Users/oswaldkid/miniforge3/envs/abmap/bin/python3"
MODELS_DIR="${TOOL_DIR}/NetSolP-1.0/PredictionServer/models"

echo "Verifying biopython in abmap env (required)..."
"${ABMAP_PYTHON}" -c "from Bio.SeqUtils.ProtParam import ProteinAnalysis; print('biopython OK')"
echo "Base setup complete. Physicochemical solubility estimation is ready."

# ── Optional: download full NetSolP ML models ─────────────────────────────────
if [[ "${1:-}" == "--download-models" ]]; then
  echo ""
  echo "Downloading full NetSolP-1.0 archive (~5.6 GB)…"
  ARCHIVE="/tmp/netsolp-1.0.ALL.tar.gz"
  curl -L -o "${ARCHIVE}" "https://services.healthtech.dtu.dk/services/NetSolP-1.0/netsolp-1.0.ALL.tar.gz"
  echo "Extracting ONNX models…"
  mkdir -p "${MODELS_DIR}"
  tar -xzf "${ARCHIVE}" --wildcards "*/models/*.onnx" --strip-components=3 -C "${MODELS_DIR}"
  echo "Installing onnxruntime + pandas into abmap env…"
  /Users/oswaldkid/miniforge3/envs/abmap/bin/pip install onnxruntime pandas --quiet
  echo "Full NetSolP ML models installed at ${MODELS_DIR}"
  rm -f "${ARCHIVE}"
fi
