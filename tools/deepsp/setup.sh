#!/usr/bin/env bash
# DeepSP uses the existing 'abmap' conda environment.
# abmap already has: ANARCI, numpy, torch.
# No additional installation needed.
set -euo pipefail

ABMAP_PYTHON="/Users/oswaldkid/miniforge3/envs/abmap/bin/python3"

if [ ! -f "${ABMAP_PYTHON}" ]; then
  echo "ERROR: abmap conda env not found at ${ABMAP_PYTHON}"
  echo "Please ensure the abmap env is set up (run tools/abmap/setup.sh first)."
  exit 1
fi

echo "Verifying DeepSP dependencies in abmap env..."
"${ABMAP_PYTHON}" -c "import numpy; from anarci import anarci; print('All dependencies OK')"
echo "DeepSP setup complete. Run with: ${ABMAP_PYTHON} run.py"
