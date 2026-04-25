# CLAUDE.md

> **Guidance file for Claude when working on this repository.**
> Keep this file updated as the project evolves. Claude should read this first before making changes.

---

## 1. Project Overview

### 1.1 What We're Building

A **visual pipeline platform for antibody design**, modeled after [n8n](https://n8n.io/). Users compose computational biology workflows by dragging tool nodes onto a canvas and wiring them together. Each node represents an antibody design tool (structure prediction, sequence design, docking, affinity estimation, etc.). Pipelines are executed by a backend that dispatches tool calls to appropriate compute resources (primarily cloud GPU instances on AWS/GCP).

Think of it as: **n8n's UX + antibody design tool ecosystem + LLM-driven pipeline authoring.**

### 1.2 Why This Exists

Antibody design workflows today are:
- Fragmented across CLI tools, Jupyter notebooks, and ad-hoc scripts
- Hard to reproduce — environment drift, tool version mismatches, manual file shuffling
- Hard to share — tribal knowledge about "which tool to run after which"
- Hard to scale — each lab reinvents orchestration

This platform gives researchers a **visual, reproducible, shareable, chat-authored** way to build and run antibody design pipelines.

### 1.3 Key Differentiators from n8n

| n8n | This platform |
|-----|---------------|
| General-purpose automation | Domain-specific: antibody design |
| Tools = API integrations (Slack, Gmail) | Tools = scientific compute (AlphaFold, RFdiffusion, ProteinMPNN, HADDOCK, Rosetta, ...) |
| Short-lived HTTP calls | Long-running GPU jobs (minutes to hours) |
| JSON-first data flow | Flexible, tool-defined data (PDB, FASTA, JSON, arbitrary artifacts) |
| Manual canvas authoring | **Canvas + chat-driven pipeline generation** (future) |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (TypeScript)                    │
│  ┌────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │ Canvas Editor  │  │  Node Palette    │  │  Chat Assistant │ │
│  │ (React Flow /  │  │  (tool icons)    │  │  (future)       │ │
│  │  Rete.js)      │  │                  │  │                 │ │
│  └────────────────┘  └──────────────────┘  └─────────────────┘ │
│                    Pipeline graph (JSON)                         │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST / WebSocket
┌──────────────────────────────▼──────────────────────────────────┐
│                        BACKEND (Python)                          │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ API Gateway │  │ Pipeline     │  │  Tool Registry         │ │
│  │ (FastAPI)   │→ │ Orchestrator │→ │  (tool specs, I/O      │ │
│  │             │  │ (DAG exec)   │  │   schemas, endpoints)  │ │
│  └─────────────┘  └──────┬───────┘  └────────────────────────┘ │
│                          │                                       │
│                          ▼                                       │
│                   ┌──────────────┐    ┌────────────────────┐   │
│                   │ Job Queue    │───▶│ Artifact Store     │   │
│                   │ (Celery /    │    │ (S3 / GCS:         │   │
│                   │  Redis)      │    │  PDBs, FASTAs, ...)│   │
│                   └──────┬───────┘    └────────────────────┘   │
└──────────────────────────┼───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                    COMPUTE LAYER (Cloud GPU)                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ...     │
│  │ AlphaFold    │  │ RFdiffusion  │  │ ProteinMPNN  │           │
│  │ worker       │  │ worker       │  │ worker       │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│           Each tool = HTTP/gRPC endpoint on a GPU instance        │
└───────────────────────────────────────────────────────────────────┘
```

---

## 3. Repository Layout (target)

```
/
├── CLAUDE.md                    # ← this file
├── README.md                    # user-facing intro
├── docs/
│   ├── architecture.md
│   ├── tool-spec.md             # how to define a new tool
│   └── pipeline-format.md       # pipeline graph JSON schema
│
├── backend/                     # Python, FastAPI
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py              # FastAPI entry
│   │   ├── api/                 # REST routes
│   │   │   ├── pipelines.py
│   │   │   ├── tools.py
│   │   │   ├── runs.py
│   │   │   └── artifacts.py
│   │   ├── core/                # orchestration logic
│   │   │   ├── dag.py           # graph representation & topo sort
│   │   │   ├── executor.py      # runs a pipeline
│   │   │   ├── scheduler.py     # decides where/when a node runs
│   │   │   └── state.py         # run state, checkpoints
│   │   ├── tools/               # tool registry & adapters
│   │   │   ├── registry.py      # loads tool specs
│   │   │   ├── base.py          # ToolAdapter abstract class
│   │   │   └── adapters/        # one module per tool
│   │   │       ├── alphafold.py
│   │   │       ├── rfdiffusion.py
│   │   │       └── ...
│   │   ├── storage/             # artifact persistence
│   │   │   ├── s3.py
│   │   │   └── local.py
│   │   ├── models/              # SQLAlchemy / Pydantic
│   │   └── workers/             # Celery tasks
│   └── tests/
│
├── frontend/                    # TypeScript, React
│   ├── package.json
│   ├── src/
│   │   ├── canvas/              # pipeline editor
│   │   │   ├── Canvas.tsx
│   │   │   ├── NodeRenderer.tsx
│   │   │   └── EdgeRenderer.tsx
│   │   ├── palette/             # draggable tool icons
│   │   ├── chat/                # LLM pipeline authoring (future)
│   │   ├── runs/                # run monitoring, logs, artifacts
│   │   ├── api/                 # backend client
│   │   └── types/               # shared types (generated from backend)
│   └── public/
│
├── tools/                       # tool container definitions
│   ├── alphafold/
│   │   ├── Dockerfile
│   │   ├── server.py            # HTTP adapter around the tool
│   │   └── tool.yaml            # tool spec (I/O schema, icon, etc.)
│   ├── rfdiffusion/
│   └── ...
│
├── infra/                       # terraform / k8s / docker-compose
│   ├── terraform/
│   ├── k8s/
│   └── docker-compose.yml       # local dev
│
└── scripts/                     # dev utilities
```

---

## 4. Core Concepts

### 4.1 Tool

A **Tool** is a single computational step (e.g., "predict structure with AlphaFold"). Every tool is defined by a `tool.yaml` spec:

```yaml
id: alphafold_monomer
name: AlphaFold (monomer)
version: 2.3.2
category: structure_prediction
icon: alphafold.svg

inputs:
  - name: sequence
    type: fasta            # tool-defined type; registry resolves compatibility
    required: true
  - name: num_recycles
    type: int
    default: 3

outputs:
  - name: structure
    type: pdb
  - name: plddt
    type: json

runtime:
  kind: http                # http | grpc | local_python | k8s_job
  endpoint_env: ALPHAFOLD_URL
  gpu: true
  timeout_seconds: 3600
```

The backend **Tool Registry** loads all `tool.yaml` files at startup and exposes them via `GET /api/tools`. The frontend renders them as draggable icons in the palette.

> **Flexible data flow:** We do NOT enforce a single schema between nodes. Types are declared per tool; the registry checks compatibility at wire-time (e.g., `fasta → fasta` is fine; `pdb → fasta` is rejected unless an adapter exists). Artifacts themselves live in object storage; only references (URIs + metadata) pass through the DAG.

### 4.2 Pipeline

A **Pipeline** is a DAG of tool invocations. Persisted as JSON:

```json
{
  "id": "pipeline_abc",
  "name": "Design binder vs target X",
  "nodes": [
    { "id": "n1", "tool": "rfdiffusion", "params": { "...": "..." }, "position": {"x": 100, "y": 200} },
    { "id": "n2", "tool": "proteinmpnn", "params": { "...": "..." }, "position": {"x": 400, "y": 200} },
    { "id": "n3", "tool": "alphafold_monomer", "params": {}, "position": {"x": 700, "y": 200} }
  ],
  "edges": [
    { "from": "n1.backbone", "to": "n2.structure" },
    { "from": "n2.sequence", "to": "n3.sequence" }
  ]
}
```

### 4.3 Run

A **Run** is an execution of a Pipeline. It has:
- Run status: `queued | running | succeeded | failed | cancelled`
- Per-node status + logs + artifact references
- Immutable: re-running clones the pipeline into a new Run

### 4.4 Artifact

Any output produced by a node — PDB files, FASTA files, JSON reports, numpy arrays. Stored in object storage (S3/GCS). Referenced by URI + content hash.

### 4.5 Tool Adapter

The Python class in `backend/app/tools/adapters/` that knows how to invoke a specific tool (build request, call endpoint, parse response, upload artifacts). Implements `ToolAdapter`:

```python
class ToolAdapter(Protocol):
    spec: ToolSpec
    async def invoke(self, inputs: dict, run_ctx: RunContext) -> dict: ...
```

---

## 5. Execution Model

1. User submits a Pipeline → backend validates graph (no cycles, types compatible, required inputs bound).
2. A **Run** is created; nodes enter state `queued`.
3. The **Executor** performs a topological walk. For each ready node:
   - Resolve inputs (fetch artifact URIs from upstream node outputs).
   - Dispatch to the Job Queue (Celery task).
4. A **Worker** picks up the task, invokes the Tool Adapter, which calls the tool endpoint on a GPU instance.
5. Tool produces artifacts → uploaded to object storage → URIs recorded in run state.
6. Downstream nodes become ready; repeat until the DAG is exhausted or a node fails.
7. Frontend receives live updates via WebSocket (per-node status, logs, partial artifacts).

**Failure policy (v1):** fail-fast. Node fails → run fails. Later: retries, per-branch continuation, manual intervention nodes.

---

## 6. Chat-Driven Pipeline Authoring (Future)

Planned: a chat panel where a user describes an experiment ("design a binder to PD-L1, 80 residues, predict structure and estimate affinity") and an LLM produces a pipeline JSON that populates the canvas.

Design notes for later:
- LLM sees the **Tool Registry** as its tool list (names, descriptions, I/O schemas).
- Output = pipeline JSON, validated before render.
- User can accept/edit/reject before running.
- Keep canvas as source of truth; chat is an authoring aid, not a parallel runtime.

---

## 7. Tech Stack

**Backend (Python)**
- FastAPI — REST + WebSocket
- Celery + Redis — job queue
- SQLAlchemy + Postgres — metadata (pipelines, runs, users)
- Pydantic — schemas
- boto3 / google-cloud-storage — artifacts
- pytest — tests

**Frontend (TypeScript)**
- React
- [React Flow](https://reactflow.dev/) or [Rete.js](https://retejs.org/) for the canvas (decide early — React Flow is simpler, Rete.js is more powerful)
- Zustand or Redux Toolkit — state
- TanStack Query — server state
- Tailwind — styling

**Infra**
- Docker — every tool is a container with an HTTP adapter
- Kubernetes (eventually) — for GPU scheduling
- Terraform — cloud resources
- AWS or GCP — GPU instances (A100 / H100 / L4 depending on tool)

---

## 8. Non-Goals (for now)

- ❌ Real-time multi-user co-editing of a canvas (single-user edit, share-by-link is fine)
- ❌ Custom tool authoring from inside the UI (tools are added via `tool.yaml` + Dockerfile in the repo)
- ❌ Billing, multi-tenancy, SSO (add when there are users)
- ❌ On-prem deployment story (cloud-first)

---

## 9. Build Order (suggested)

A staged path so each step is demoable:

1. **Tool spec + registry** — define the YAML format, load it, expose `GET /api/tools`. No execution yet.
2. **Static canvas** — frontend renders the palette and lets the user place/connect nodes. Save/load pipeline JSON.
3. **Single-node run** — execute one node against a mock tool (echo server). End-to-end: submit → queue → worker → artifact → display.
4. **DAG executor** — multi-node runs with topological scheduling and artifact passing.
5. **First real tool** — wrap one real tool (e.g., ESMFold — lighter than AlphaFold) in a Docker container with an HTTP adapter. Run it on a cloud GPU.
6. **Run monitoring UI** — live node status, logs, artifact previews (PDB viewer via NGL/Mol*).
7. **Add tools progressively** — RFdiffusion, ProteinMPNN, AlphaFold, docking, affinity.
8. **Chat authoring** — LLM generates pipeline JSON from natural language.

Don't build steps 4+ until 1–3 are solid. The registry + canvas + single-node loop is the spine; everything else hangs off it.

---

## 10. Conventions for Claude

When working in this repo:

- **Read this file first.** If a change contradicts something here, update this file as part of the change (or flag the contradiction).
- **Tool specs are the source of truth.** Don't hardcode tool I/O anywhere else; read from the registry.
- **Pipeline JSON is versioned.** Any change to its schema needs a migration plan (bump `schema_version`).
- **Artifacts are immutable + content-addressed.** Never mutate an existing artifact; write a new one.
- **Long-running = async.** Any tool call is assumed to be minutes-to-hours. Never block an HTTP handler on tool execution.
- **Frontend/backend types stay in sync.** Generate TS types from Pydantic models (via `datamodel-code-generator` or similar) rather than hand-maintaining two copies.
- **Adding a tool? Read `docs/adding-tools.md` first.** It documents the exact patterns (env isolation, subprocess runner, `alog` for live logs, caching, frontend checklist) that all tools in this repo follow. Don't improvise — diverging from the pattern creates maintenance burden.
- **Small PRs, one concern each.** Especially while the architecture is still settling.
- **When unsure, ask before scaffolding.** This codebase will grow slowly and deliberately; don't generate 40 files on a vague prompt.

---

## 11. Results Database

Every tool that runs automatically writes its outputs to a typed results database. This is the canonical store for all experimental results — do NOT read outputs from the run state for analysis; use the results DB instead.

### Schema

| Table | What it stores | Key links |
|---|---|---|
| `molecules` | One row per unique VH(+VL) sequence pair | root entity |
| `structures` | PDB outputs from ImmuneBuilder/ESMFold/AlphaFold | → molecule_id |
| `docking_results` | HADDOCK3 best complex + CAPRI scores | → molecule_id |
| `design_sequences` | ProteinMPNN sequences / RFdiffusion backbones | → molecule_id |
| `embeddings` | AbMAP / ESM embedding metadata | → molecule_id |

### How collection works

`app/core/results_collector.py` is called by the executor after every successful node. It:
1. Finds or creates a `MoleculeRow` from the VH/VL sequences flowing through the pipeline
2. Saves tool-specific outputs (PDB, scores, sequences) into the appropriate typed table
3. Links everything to the molecule_id — so one molecule can have N structures, M docking runs, etc.
4. Never crashes the pipeline (errors are logged and swallowed)

### Adding a new tool's outputs to the DB

In `results_collector.py`:
1. Add the tool_id to the appropriate `_*_TOOLS` set (or create a new set + handler)
2. Implement `_collect_<toolname>(run, node_id, tool_id, inputs, outputs, molecule_id)`
3. Use `AsyncSessionLocal` + the appropriate Row class to insert the row
4. Call it from `collect()` in the if/elif chain

### API

```
GET /api/results/molecules                  → list all molecules with counts
GET /api/results/molecules/{id}             → full detail (structures, docking, etc.)
GET /api/results/structures/{id}/pdb        → download PDB
GET /api/results/docking/{id}/pdb           → download docking complex PDB
```

### Frontend

The Results page (`frontend/src/results/ResultsPage.tsx`) is accessible via the "Results" button in the top bar. It auto-refreshes every 10 seconds and shows all molecules with their linked data.

---

## 12. Open Questions (to resolve as we go)

- React Flow vs Rete.js for the canvas?
- Celery vs Dramatiq vs Temporal for the job queue? (Temporal is tempting for long-running workflows with retries, but heavy.)
- Per-tool Docker images vs a base image with tool plugins?
- How to version tools (tag + pin in pipeline JSON so old pipelines keep working)?
- Caching: should we memoize node outputs by (tool_version, inputs_hash)? Would massively speed up iterative design.
- Where does the chat LLM run — Anthropic API, self-hosted, user-supplied key?

Add answers here as they're decided.
