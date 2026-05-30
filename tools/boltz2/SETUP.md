# Boltz2 Setup

Boltz2 (Passaro et al. 2025) predicts protein structures and binding affinities for
protein-ligand complexes. https://github.com/jwohlwend/boltz

## Requirements

**NVIDIA GPU (recommended):** A100 / H100 / L40S with ≥ 48 GB VRAM + CUDA 12.1+
- Full-length antibody + ligand: ~1–2 min

**Apple Silicon (M1/M2/M3/M4 — MPS via PyTorch):** supported, no extra setup
- PyTorch Lightning auto-detects MPS when `--accelerator gpu` is passed
- Full-length antibody + ligand (~230 aa total): ~43 min on MPS
- Short sequences (≤ 30 aa per chain): ~90 s on MPS
- **No MLX port exists** as of mid-2026. MPS via PyTorch is the native Mac GPU path.

## Install

```bash
cd tools/boltz2
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install "boltz[cuda]" uvicorn fastapi pydantic
# Model weights are downloaded automatically on first run
```

## Start the server

```bash
cd tools/boltz2
.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8010
```

Add to `backend/.env`:
```
BOLTZ2_URL=http://localhost:8010
```

## Health check

```bash
curl http://localhost:8010/health
# {"status":"ok"}
```

## Test prediction

```bash
curl -s http://localhost:8010/predict \
  -H "Content-Type: application/json" \
  -d '{"sequence":"MAQQSPYSAAMA","ligand_smiles":"CC(=O)O"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('PDB:', len(d['structure']), 'chars; prob:', d['binding_probability'])"
```

## CPU-only (no GPU) — slow but functional

```bash
.venv/bin/pip install boltz   # without [cuda]
```

## NVIDIA NIM (cloud / Docker alternative)

If you have an NGC API key, you can use the containerised Boltz2 NIM:

```bash
docker run --rm --name boltz2 --runtime=nvidia --shm-size=16G \
  -e NGC_API_KEY=$NGC_API_KEY \
  -p 8010:8000 \
  nvcr.io/nim/mit/boltz2:latest
```

The NIM endpoint differs from this server — set `BOLTZ2_URL` to the NIM host.
