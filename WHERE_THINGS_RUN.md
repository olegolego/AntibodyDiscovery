# Where Everything Runs

## Quick map

```
Browser (localhost:5173)
  └─► Backend API (localhost:8000)
        ├─► SQLite DB  (backend/protein_design.db)
        ├─► Local tools (subprocess / in-process)
        │     ├─ ImmuneBuilder   — Python in-process, CPU, macOS
        │     ├─ RFdiffusion     — subprocess in dedicated venv, CPU (no GPU/MPS yet)
        │     ├─ AlphaFold       — EBI REST API (HTTPS, external)
        │     ├─ Sequence Input  — echo passthrough, no compute
        │     └─ Target Input    — echo passthrough, no compute
        └─► Remote tools (HTTP, not yet running)
              ├─ ESMFold         — http://localhost:8004  (needs GPU server)
              ├─ ProteinMPNN     — http://localhost:8003  (needs GPU server)
              └─ AbMAP           — http://localhost:8005  (needs GPU server)
```

---

## Frontend

| What | Where | How to start |
|------|-------|-------------|
| React + ReactFlow UI | `frontend/` | `npm run dev` → **http://localhost:5173** |
| Vite dev proxy | rewrites `/api/*` → `localhost:8000`, `/ws/*` → `ws://localhost:8000` | automatic |

---

## Backend

| What | Where | How to start |
|------|-------|-------------|
| FastAPI server | `backend/` | `uvicorn app.main:app --reload --port 8000` |
| SQLite database | `backend/protein_design.db` | created automatically on first start |
| Tool registry | `tools/*/tool.yaml` loaded at startup | automatic |
| Analysis rows | same SQLite DB (`node_analyses` table) | automatic |

REST endpoints:
- `GET  /api/tools/`                              — list all registered tools
- `POST /api/pipelines/`                          — save pipeline
- `POST /api/runs/`                               — submit a run
- `GET  /api/runs/{id}`                           — run status
- `GET  /api/analysis/runs/{run_id}/nodes/{node_id}` — per-node analysis
- `WS   /ws/runs/{run_id}`                        — live status stream

---

## Tools — where each one actually executes

### Sequence Input / Target Input
- **Runtime:** `local_python` — EchoAdapter, runs in the FastAPI process
- **Compute:** none (passthrough)
- **Files:** `tools/sequence_input/`, `tools/target_input/`

### ImmuneBuilder (ABodyBuilder2 / NanoBodyBuilder2)
- **Runtime:** `local_python` — runs **inside the FastAPI process**
- **Compute:** CPU only (no GPU required, ~30–90 s per model on Mac)
- **Dependencies:** `ImmuneBuilder`, `anarci`, `hmmer` (brew), `pdbfixer`, `openmm`
- **Models:** downloaded automatically to `~/.ImmuneBuilder/`
- **Files:** `tools/immunebuilder/`, `backend/app/tools/adapters/immunebuilder.py`

### RFdiffusion
- **Runtime:** `local_python` — launched as a **subprocess** from the FastAPI process
- **Compute:** CPU only on macOS (DGL does not support MPS; CUDA needed for real speed)
- **Python env:** isolated venv at `tools/rfdiffusion/venv/`
- **Model weights:** `tools/rfdiffusion/models/` — `Base_ckpt.pt`, `Complex_base_ckpt.pt` (461 MB each)
- **Script:** `tools/rfdiffusion/RFdiffusion/scripts/run_inference.py`
- **Files:** `tools/rfdiffusion/`, `backend/app/tools/adapters/rfdiffusion.py`
- **Expected time:** ~10–60 min on CPU; ~1–5 min on A100

### AlphaFold
- **Runtime:** `local_python` — calls the **EBI AlphaFold REST API** over HTTPS
- **Compute:** EBI's cloud (external); input is a UniProt accession ID, not a raw sequence
- **URL:** `https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}`
- **Files:** `tools/alphafold/`, `backend/app/tools/adapters/alphafold.py`

### ESMFold *(not yet running)*
- **Runtime:** `http` — expects a running HTTP server
- **Default URL:** `http://localhost:8004` (override with `ESMFOLD_URL` env var)
- **Compute:** GPU required (A100/H100 recommended)
- **Files:** `tools/esmfold/`, `backend/app/tools/adapters/esmfold.py`

### ProteinMPNN *(not yet running)*
- **Runtime:** `http` — expects a running HTTP server
- **Default URL:** `http://localhost:8003` (override with `PROTEINMPNN_URL` env var)
- **Compute:** GPU recommended
- **Files:** `tools/proteinmpnn/`, `backend/app/tools/adapters/proteinmpnn.py`

### AbMAP *(not yet running)*
- **Runtime:** `http` — expects a running HTTP server
- **Default URL:** `http://localhost:8005` (override with `ABMAP_URL` env var)
- **Compute:** CPU (embedding model)
- **Files:** `tools/abmap/`, `backend/app/tools/adapters/abmap.py`

---

## Environment variables (backend/.env)

```
DATABASE_URL=sqlite+aiosqlite:///./protein_design.db

# Remote tool endpoints (only needed when those tools are running)
ESMFOLD_URL=http://localhost:8004
PROTEINMPNN_URL=http://localhost:8003
ABMAP_URL=http://localhost:8005

# Storage (defaults to local ./artifacts/)
STORAGE_BACKEND=local
LOCAL_ARTIFACT_DIR=./artifacts

# Future cloud storage
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
S3_ARTIFACT_BUCKET=
```

---

## What runs where — summary table

| Tool | Execution | Machine | GPU | Speed |
|------|-----------|---------|-----|-------|
| Sequence Input | in-process (echo) | backend server | no | instant |
| Target Input | in-process (echo) | backend server | no | instant |
| ImmuneBuilder | in-process Python | backend server | no (CPU) | ~1–3 min / model |
| RFdiffusion | subprocess (own venv) | backend server | no (CPU) | ~10–60 min |
| AlphaFold | EBI REST API | EBI cloud | EBI's | ~1–5 s (lookup) |
| ESMFold | HTTP call | GPU server | yes | ~30 s on A100 |
| ProteinMPNN | HTTP call | GPU server | recommended | ~10–60 s |
| AbMAP | HTTP call | GPU server | no | ~5–30 s |
