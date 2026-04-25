# ImmuneBuilder — Setup Guide

**What it does:** Antibody and nanobody structure prediction. Runs locally, CPU-only (~2 min per prediction).

**Environment:** Shared backend venv (`backend/.venv`). No isolated venv needed.

---

## Requirements

- Python 3.10
- Backend venv already created (`cd backend && python3.10 -m venv .venv && .venv/bin/pip install -e .`)
- ~200 MB disk space for model weights (downloaded once on first use)

---

## Install

```bash
# From repo root
bash tools/immunebuilder/setup.sh
```

The script:
1. Installs `ImmuneBuilder` and `anarci` into `backend/.venv`
2. Verifies the imports
3. Pre-downloads model weights (runs `ABodyBuilder2(model_ids=[1])` once so the 200 MB weights are cached before the first real job)

### Manual steps (if the script fails)

```bash
backend/.venv/bin/pip install ImmuneBuilder anarci

# Verify
backend/.venv/bin/python -c "from ImmuneBuilder import ABodyBuilder2; print('ImmuneBuilder ok')"
backend/.venv/bin/python -c "import anarci; print('ANARCI ok')"

# Pre-download weights
backend/.venv/bin/python -c "
from ImmuneBuilder import ABodyBuilder2
b = ABodyBuilder2(model_ids=[1])
print('Weights ready')
"
```

---

## Verify

```bash
backend/.venv/bin/python -c "
from ImmuneBuilder import ABodyBuilder2, NanoBodyBuilder2
print('ImmuneBuilder ready')
"
```

---

## Known issues

| Issue | Fix |
|---|---|
| `AttributeError: module 'numpy' has no attribute 'bool'` | `pip install 'numpy<2'` |
| `OpenMM not found` — refinement step skipped | Expected. The adapter falls back to unrefined structures gracefully. Install OpenMM via `conda install -c conda-forge openmm` if you want refined outputs. |
| ANARCI numbering fails on lambda chains | The adapter falls back to nanobody mode automatically. Use kappa-chain defaults (trastuzumab VH/VL) for full antibody runs. |
| `L chain not recognised` | Same fallback as above — check the light chain is a true VL (>80 AA, starts with Gln or Glu). |

---

## Model weights location

Weights are cached by PyTorch in `~/.cache/torch/` on the first run.
To pre-warm on a new machine: `bash tools/immunebuilder/setup.sh`.

---

## Cache

Results are cached in `tools/immunebuilder/cache.db` (SQLite).
Cache key = SHA-256(heavy_chain + light_chain + num_models) + tool_version.
To clear: `rm tools/immunebuilder/cache.db`
