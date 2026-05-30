# Paper-to-Pipeline Prompt

> **How to use:** Run Claude Code and provide this file as your system context. Then attach a PDF of the paper you want to implement. Claude will walk through every phase below end-to-end without requiring further input.
>
> Trigger phrase: *"Add the pipeline from this paper: [attach PDF]"*

---

## Phase 0 — Read and understand the paper

1. Read the full PDF. Extract:
   - **Paper title, authors, year, journal / preprint server, DOI / arXiv ID.**
   - **Tools / models used**: list every computational tool named (including baselines). For each, note:
     - Official name and version
     - Input format and output format as described in the Methods section
     - Whether it requires a GPU
     - Whether it requires a separate server or is a Python library
   - **Pipeline topology**: sketch a DAG — which tool feeds into which, what data flows on each edge. Every edge must be traceable to a sentence or figure in the paper. Copy the exact quote.
   - **Evaluation / benchmark**: which dataset does the paper use to validate the method? Is it public? Note the accession ID, URL, or download command.
   - **Improvement ideas**: note anything in the paper that the platform could benefit from (e.g. new scoring function, new filtering criterion, alternative backbone) but that the paper itself does not implement.

2. Write a short summary block (Markdown, ≤ 200 words) covering: what the paper achieves, what tools it uses, and what the pipeline looks like. Print this to the terminal so the user can confirm the interpretation before any code is written.

3. **Stop and wait for confirmation** if anything is ambiguous (e.g., two tools with the same name, an edge that is not explicitly stated, a tool with no public implementation).

---

## Phase 1 — Audit existing tools

For each tool identified in Phase 0, check whether it already exists:

```bash
ls tools/          # list all tool directories
```

For any tool that **does** exist, verify the `tool.yaml` I/O matches what the paper expects. If there is a mismatch (e.g., the paper pipes a PDB directly where the tool expects a sequence), note it as a **gap** — you will need a converter node or a parameter update.

Produce a table:

| Tool | Status | Notes |
|---|---|---|
| `tool_a` | **present** | I/O matches |
| `tool_b` | **present** | paper expects `pdb` output but tool emits `json` — gap |
| `tool_c` | **missing** | need to add |

---

## Phase 2 — Add missing tools

For each **missing** tool, follow `docs/adding-tools.md` in exact order. Do not skip steps.

### 2a. Research (Step 1 of adding-tools.md)

- Search for the official GitHub repo. Prefer the repo linked in the paper over forks.
- **NEVER write stub implementations.** Clone the actual repo (or pip-install the real package). Use the real CLI / API. If you can't find an install-ready implementation, say so and wait for user guidance.
- Read the README, `examples/`, and `tests/` to answer: Python API, input/output format, confidence metric, GPU requirement, known failure modes, dependencies.
- If a pip-installable package exists, prefer Pattern A (in-process). If it has dependency conflicts or requires its own Python version, use Pattern B (subprocess). If it serves a REST API, use Pattern C (HTTP).

### 2b. Create `tools/<name>/tool.yaml`

Follow the YAML template in `docs/adding-tools.md § 3`. Rules:
- `id` must be unique across all `tool.yaml` files — verify with `grep -r "^id:" tools/ | sort`.
- Always provide `default:` values for `fasta`/`pdb` inputs (use a real trastuzumab VH/VL sequence as default). For large defaults, use `default_file:`.
- If the tool processes a **batch of antibody variants**, use the standard batch token (`sequences` JSON field) defined in § 3.5.
- If the tool is a **sequence embedding** model, use the exact I/O contract from § 3.6 and copy inputs/outputs from `tools/ablang/tool.yaml`.

### 2c. Environment setup

- Pattern A: install into `backend/.venv`. Verify import.
- Pattern B: create `tools/<name>/setup.sh` and `tools/<name>/run.py`. Run setup and verify the script exits 0.
  - **IMPORTANT**: Always use `_TOOL_PYTHON = Path(__file__).parents[3] / ".venv" / "bin" / "python"` (absolute, not `Path("backend/.venv/...")`).
  - If the tool uses stdlib only, point to the backend venv at `Path(__file__).parents[3] / ".venv" / "bin" / "python"`.
  - If the tool needs its own deps (torch, prody, etc.), create `tools/<name>/.venv` in `setup.sh`, then point `_TOOL_PYTHON` there using `Path(__file__).parents[3] / "tools" / "<name>" / ".venv" / "bin" / "python"` — wait, that's wrong. Use: `Path(__file__).resolve().parents[3] / "tools" / tool_id / ".venv" / "bin" / "python"` or an env-var override. See `ligand_mpnn.py` adapter as the reference.
- Pattern C: document the server start command in `tools/<name>/SETUP.md`. Verify `/health` returns `{"status": "ok"}`.
  - The adapter must import `settings` from `app.config` and use `settings.<toolname>_url`.
  - Add `<toolname>_url: str = "http://localhost:PORT"` to `backend/app/config.py`.
  - Add `<TOOLNAME>_URL=http://localhost:PORT` to `backend/.env`.

### 2d. Write `backend/app/tools/adapters/<name>.py`

Use the correct adapter template from § 5 of adding-tools.md. Mandatory:
- Lazy imports inside `invoke()`.
- `ToolCache` wired (check get before run, put after success).
- `await run_ctx.alog()` at start, each major step, and end.
- For Pattern B: pass `run_id=run_ctx.run_id` to `run_tool_subprocess`.
- For multi-output tools: pad unused slots with `None`.
- **Type mismatch handling**: when a tool receives input from an upstream tool whose output type differs from what it expects, coerce in the adapter `invoke()`. Example: `esmfold` receives `sequence` that may be `str`, `list[str]` (from ProteinMPNN), or `list[dict]` (from Fuse fusions — extract `.sequence` key). Handle all cases rather than assuming the wire type is always correct.

### 2e. Register the adapter in `backend/app/workers/tasks.py`

Add to `_ADAPTER_MAP`:
```python
"tool_name": ("app.tools.adapters.tool_name", "ToolNameAdapter"),
```

### 2f. If the tool outputs a PDB structure — follow § 6 of adding-tools.md exactly:
- Add to `_ANALYSIS_TOOLS` in `executor.py`.
- Add an inline `NodeAnalysisRow` save block (use the direct insert pattern — do NOT use `_save_analysis()` for structure tools).
- Add to the post-run loop skip list in `executor.py`.
- Update `_extract_metrics()` and `_TOOL_NAMES` in `runs.py`.
- Update `hasAnalysis` in `RunPanel.tsx`.

### 2g. Register in `results_collector.py` (§ 7)

Add to the relevant set (`_STRUCTURE_TOOLS`, `_DESIGN_TOOLS`, `_EMBEDDING_TOOLS`) and implement a handler if the output format is non-standard.

### 2h. Register features in `tool_features.py` (§ 7.5)

Add a `register()` block for every important scalar output.

### 2i. Add paper reference to `frontend/src/playground/papers.ts`

### 2j. Add a test to `scripts/test_all_tools.py`

For each new tool, add `test_<tool_id>()` following the pattern in § 13 of adding-tools.md.

---

## Phase 3 — Test each new tool in isolation

Run the test suite for each newly added tool:

```bash
python3 scripts/test_all_tools.py   # or the specific group for your tool
```

For structure tools also run:
```bash
python3 scripts/test_structure_tools.py
```

Then verify the analysis endpoint returns real PDB (not `"__artifact__"`):
```bash
RUN_ID="<from test output>"
NODE_ID="<from test output>"
curl -s http://localhost:8000/api/analysis/runs/$RUN_ID/nodes/$NODE_ID/ | \
  python3 -c "import json,sys; d=json.load(sys.stdin); s=d.get('structure',''); print(f'PDB chars={len(s)}, real={not s.startswith(\"__\")}')"
```

Run each tool twice with identical inputs to confirm caching:
```bash
# Second run should log "Cache hit" and return in < 1s
```

**Do not proceed to Phase 4 until all new tools pass Phase 3.**

Log any bugs found during testing in [BUGS section](#bugs) at the bottom of this document. Include: tool, symptom, root cause, fix applied.

---

## Phase 4 — Build the pipeline

### 4a. Create a pipeline seed script

Create `scripts/seed_<paper_slug>_pipeline.py`. Use existing seed scripts in `scripts/` as templates (e.g. `seed_full_pipelines.py`, `seed_modular_dnn_pipeline.py`).

For each node:
- `tool`: the `id` from `tool.yaml`
- `params`: default parameters from the paper (Methods section)
- `position`: lay out left-to-right following the paper's figure

For each edge:
- `source`: `"<node_id>.<output_name>"` — must match the `outputs` list in `tool.yaml`
- `target`: `"<node_id>.<input_name>"` — must match the `inputs` list in `tool.yaml`
- Add a comment quoting the sentence or figure from the paper that justifies the connection:
  ```python
  # Paper §2.3: "The backbone generated by RFdiffusion is passed directly to ProteinMPNN..."
  edges.append({"source": "n1.backbone", "target": "n2.structure"})
  ```

### 4b. Run the seed script and verify

```bash
python3 scripts/seed_<paper_slug>_pipeline.py
```

Open the frontend. The pipeline should appear in the pipeline list. Load it on the canvas. All nodes and edges should render without errors.

### 4c. Execute the pipeline end-to-end — MANDATORY, do not skip

**Submit the run immediately after seeding.** Do not wait for user confirmation — run it now and report results.

```python
import json, urllib.request, time

pipeline = { ... }  # same dict as seeded

data = json.dumps(pipeline).encode()
req = urllib.request.Request("http://localhost:8000/api/runs/", data=data,
                             headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(req, timeout=30) as r:
    run_id = json.loads(r.read())["id"]

TERMINAL = {"succeeded", "failed", "cancelled"}
while True:
    with urllib.request.urlopen(f"http://localhost:8000/api/runs/{run_id}/", timeout=30) as r:
        run = json.loads(r.read())
    if run["status"] in TERMINAL:
        break
    time.sleep(10)
```

Verify and report **to the user** immediately:
- Every node transitions: `queued → running → succeeded`
- No node fails silently (check `error` fields)
- Downstream nodes received upstream outputs — print output keys and sizes for each node
- For structure-output nodes: confirm the analysis endpoint returns real PDB (not `__artifact__`):
  ```bash
  curl -s http://localhost:8000/api/analysis/runs/$RUN_ID/nodes/$NODE_ID/ | \
    python3 -c "import json,sys; s=json.load(sys.stdin).get('structure',''); print(f'PDB chars={len(s)}, real={not s.startswith(\"__\")}')"
  ```

**Report format** — always print this summary to the user before declaring done:

```
Run ID   : <run_id>
Status   : succeeded / failed
Duration : ~Xs

Node results:
  ✓ rfdiffusion  → backbone: 12 chars (__artifact__), metadata: {num_designs: 1, ...}
  ✓ proteinmpnn  → sequence: list[3] (60-aa sequences), scores: [2.24, 1.09, 1.07]
  ✓ esmfold      → structure: 19482 chars (real PDB ✓), plddt: {...}

ESMFold PDB: 19482 chars, real=True ✓
```

**Do not report a pipeline as done unless you have run it and shown the above output.**

---

## Phase 5 — Test on benchmark data

### 5a. If the paper provides an open dataset

Identify the dataset from Phase 0. Download or locate it:
```bash
# Example: SAbDab, OAS, PDB, Zenodo, Supplementary files
wget <download_url> -O data/<dataset_name>.ext
```

Prepare the data as a pipeline input (convert to the format the first node expects — FASTA, PDB, or the standard batch token JSON).

Run the pipeline on the dataset. Record:
- Number of inputs processed
- Key metrics (whatever the paper reports: RMSD, success rate, affinity, etc.)
- Compare to the paper's reported values (note any expected deviation due to different random seeds, environment, or hardware)

### 5b. If no open dataset is available

Use the existing data already in the system:
- `tools/data/` — existing test sequences and structures
- `scripts/test_all_tools.py` default sequences (trastuzumab VH/VL)
- Any dataset seeded into the DB by the existing seed scripts

Run the pipeline on this data. Report outputs. Note explicitly: "No open benchmark dataset was available; tested on internal default sequences."

### 5c. Output report

Print a Markdown table:

| Metric | Paper value | This run | Delta |
|---|---|---|---|
| RMSD (Å) | 1.2 | 1.4 | +0.2 |
| Success rate | 78% | 75% | -3% |

Acceptable deltas: ≤ 10% relative difference. Flag anything larger for investigation.

---

## Phase 6 — Report improvements

List every improvement idea noted in Phase 0, plus any discovered during implementation. Format:

```
### Idea: <title>
**Source:** Paper §X.Y / observed during testing
**What:** One sentence describing the idea.
**Why it helps:** Expected benefit.
**Effort:** low / medium / high
**Risk:** low / medium / high (would it break existing pipelines?)
```

Do NOT implement these without explicit user confirmation.

---

## BUGS

Record every bug found during Phases 2–5 here. Do not delete fixed bugs — mark them resolved.

```
### BUG-001
**Tool:** <tool_id>
**Phase:** 3 — isolation test
**Symptom:** <what went wrong>
**Root cause:** <why it happened>
**Fix:** <what was changed>
**Status:** RESOLVED / OPEN
```

---

## Checklist — final verification before handing off

```
[ ] All tools from the paper are present in tools/ and pass test_all_tools.py
[ ] Each new adapter has ToolCache (get before / put after)
[ ] Structure tools have inline NodeAnalysisRow save + skip in post-run loop
[ ] All tool.yaml have working defaults (drag-drop → Run works with zero config)
[ ] TypeScript compiles: cd frontend && npx tsc --noEmit
[ ] Backend starts cleanly: backend/.venv/bin/uvicorn app.main:app --reload
[ ] Seed script creates a pipeline visible in the UI
[ ] Pipeline runs end-to-end: all nodes succeed, edges turn green
[ ] Benchmark test complete (or explicitly noted as unavailable)
[ ] Improvement ideas listed (not implemented)
[ ] All bugs logged with root cause and fix status
[ ] Paper added to frontend/src/playground/papers.ts
```
