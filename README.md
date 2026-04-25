# Protein Design Platform

A visual pipeline platform for antibody design — drag-and-drop tool nodes, wire them together, run on cloud GPUs.

## Quick start (local dev)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # edit as needed
uvicorn app.main:app --reload
```

API available at `http://localhost:8000`. Swagger UI at `http://localhost:8000/docs`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI available at `http://localhost:5173`.

### Full stack via Docker Compose

```bash
cd infra
docker compose up
```

## Adding a new tool

1. Create `tools/<tool-name>/tool.yaml` following the existing examples.
2. Add an adapter in `backend/app/tools/adapters/<tool-name>.py`.
3. Register the adapter in `backend/app/workers/tasks.py`.
4. (Optional) Add a Dockerfile in `tools/<tool-name>/` for the GPU worker.

See `CLAUDE.md` for full architecture documentation.
