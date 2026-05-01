# Adding a New Tool

A step-by-step playbook based on shipping ImmuneBuilder, HADDOCK3, AbMAP, ESMFold, RFdiffusion, and ProteinMPNN. Follow in order.

---

## 1. Research the tool

Before writing code, answer these from the tool's GitHub repo and paper:

| What | Where to look |
|---|---|
| Actual Python API | `README`, example scripts, `tests/` |
| Input format | Raw string? dict? file path? FASTA headers? |
| Output format | PDB file? numpy array? dict? |
| Confidence metric | B-factor, pLDDT, RMSD, log-likelihood — **don't guess** |
| Ensemble / multi-output mode | ImmuneBuilder: run once, get 4 ranked models |
| Known failure modes | Search Issues for errors you'll hit |
| Dependencies | Heavy? GPU? OpenMM? HMMER? Conflicts with numpy? |

**Run the tool in a notebook first.** Know what `.predict()` returns before writing the adapter.

---

## 2. Choose a runtime pattern

There are three patterns. Pick one:

| Pattern | When to use | Examples |
|---|---|---|
| **A — in-process** | Library with no dep conflicts, installed in backend venv | ImmuneBuilder |
| **B — subprocess** | Own venv required (dep conflicts, CLI binary, specific Python version) | HADDOCK3 |
| **C — HTTP** | Tool runs as a separate server (GPU server, remote instance) | AbMAP, ESMFold, ProteinMPNN |

---

## 3. Define the tool spec (`tools/<name>/tool.yaml`)

```yaml
id: my_tool
name: My Tool
version: "1.0"
category: structure_prediction   # input | structure_prediction | structure_design
                                 # sequence_design | sequence_embedding | docking | toolbox | debug
description: >
  One sentence. What it does and when to use it. Mention key limits (CPU only, max length, etc.)

inputs:
  - name: sequence
    type: fasta           # fasta | pdb | int | float | bool | str | json
    required: true
    default: "EVQLVES..."  # ALWAYS provide a working default for fasta/pdb inputs
    description: "VH sequence, single-letter AA, no FASTA headers."

  - name: num_models
    type: int
    required: false
    default: 4

outputs:
  - name: structure
    type: pdb
  - name: confidence
    type: json

runtime:
  kind: local_python       # local_python | http | grpc
  gpu: false
  timeout_seconds: 300
```

**Rules:**
- `id` must be unique and match the key in `_ADAPTER_MAP` in `tasks.py`
- Always provide `default:` values for `fasta`/`pdb` inputs — users drag the node and click Run immediately
- For large PDB/FASTA defaults (> 512 bytes), use `default_file:` instead of `default:` — the registry stores it server-side and returns a `__default_file__:` sentinel so the API payload stays small:
  ```yaml
  - name: antigen
    type: pdb
    default_file: spike_rbd.pdb    # file lives at tools/<name>/spike_rbd.pdb
  ```
- List each ranked output separately (`structure_1`, `structure_2`, …) — not one combined blob
- Don't list large intermediate files as outputs

---

## 4. Environment setup

### Pattern A — backend venv (in-process)

```bash
cd backend && source .venv/bin/activate
pip install mytool "numpy<2"    # pin numpy<2 if the tool uses torch < 2.x
python -c "from mytool import Model; print('ok')"
```

Pre-download weights (they won't re-download at runtime):
```bash
python -c "from mytool import Model; Model()"
```

### Pattern B — isolated venv (subprocess)

**1. Create `tools/<name>/setup.sh`:**

```bash
#!/usr/bin/env bash
set -e
TOOL_DIR="$(cd "$(dirname "$0")" && pwd)"
python3.10 -m venv "$TOOL_DIR/.venv"
"$TOOL_DIR/.venv/bin/pip" install -q --upgrade pip setuptools wheel certifi
CERT_PATH=$("$TOOL_DIR/.venv/bin/python" -c "import certifi; print(certifi.where())")
SSL_CERT_FILE=$CERT_PATH REQUESTS_CA_BUNDLE=$CERT_PATH \
  "$TOOL_DIR/.venv/bin/pip" install -r "$TOOL_DIR/requirements.txt"
echo "OK"
```

**2. Create `tools/<name>/run.py`:**

The subprocess runner (`subprocess_runner.py`) invokes this script with `-u` (unbuffered) and `PYTHONUNBUFFERED=1`. It reads JSON from stdin and writes JSON to stdout. Progress goes to stderr — every stderr line is forwarded live to the RunPanel terminal.

```python
#!/usr/bin/env python3
"""<Tool> subprocess entry point. Reads JSON from stdin, writes JSON to stdout."""
import json, sys
from pathlib import Path

def _progress(msg: str) -> None:
    """Print a line to stderr — streamed live to the terminal UI."""
    print(msg, file=sys.stderr, flush=True)

def _run(inputs: dict) -> dict:
    from mytool import Model
    _progress(f"Loading model…")
    model = Model()
    _progress(f"Running inference…")
    result = model.predict(inputs["sequence"])
    _progress("Done.")
    return {"structure": result.pdb, "scores": result.scores}

if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        outputs = _run(inputs)
    except Exception as exc:
        json.dump({"error": str(exc)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(outputs, sys.stdout)
    sys.stdout.flush()
```

**Key rules for `run.py`:**
- Always `flush=True` on stderr prints
- Write errors as `{"error": "..."}` JSON to stdout before `sys.exit(1)` — the runner parses this for the user-facing error message
- The venv must be at `tools/<name>/.venv/` — the runner looks there automatically
- Any binaries the tool needs (e.g. `pdb_tools`, `ANARCI`) must be on PATH. Prepend the venv bin dir:
  ```python
  _VENV_BIN = str(Path(sys.executable).parent)
  _ENV = {**os.environ, "PATH": f"{_VENV_BIN}:{os.environ.get('PATH', '')}"}
  # pass env=_ENV to all subprocess calls
  ```

### Pattern C — HTTP server

The tool runs as a separate process (locally or on a GPU instance). It must expose a `/health` endpoint (returns `{"status": "ok"}`) and a POST endpoint for inference.

**Server requirements:**
- `GET /health` → `{"status": "ok"}` — used for health checks before every request
- `POST /embed` (or `/predict`, `/design`) → JSON response
- Serve with uvicorn: `uvicorn server:app --host 0.0.0.0 --port <PORT>`

**Environment gotchas (learned from AbMAP):**
- If the tool uses torch ≤ 2.2, pin `numpy<2` — NumPy 2.x breaks the ABI
- If the tool calls CLI binaries (e.g. `ANARCI`), the binary must be on PATH when starting the server: `PATH="/path/to/env/bin:$PATH" uvicorn server:app ...`
- Set any required env vars (`ABMAP_HOME`, `MODEL_DIR`, etc.) before launching
- Add the URL to `backend/.env`: `MYTOOL_URL=http://localhost:800X`
- Add the config field to `backend/app/config.py`: `mytool_url: str = "http://localhost:800X"`

**Starting the server** — document the exact command in `tools/<name>/SETUP.md`:
```bash
MYTOOL_HOME=/path/to/weights \
PATH="/path/to/conda/env/bin:$PATH" \
/path/to/conda/env/bin/uvicorn server:app --host 0.0.0.0 --port 800X
```

---

## 5. Write the adapter (`backend/app/tools/adapters/<name>.py`)

### Pattern A — in-process

```python
"""MyTool adapter — <one-line description>."""
import os, tempfile
from typing import Any
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache

class MyToolAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="my_tool", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        sequence = str(inputs.get("sequence", "")).strip()
        if not sequence:
            raise ValueError("sequence is required")

        cache_inputs = {"sequence": sequence}
        cached = self._cache.get(cache_inputs)
        if cached is not None:
            run_ctx.log("Cache hit")
            return cached

        run_ctx.log(f"Input: {len(sequence)} AA")
        from MyTool import Predictor  # lazy import — server starts even if not installed

        with tempfile.TemporaryDirectory() as tmpdir:
            result = Predictor().predict({"H": sequence})
            result.save_all(tmpdir)
            pdb_text = open(os.path.join(tmpdir, "output.pdb")).read()

        outputs = {"structure": pdb_text}
        self._cache.put(cache_inputs, outputs)
        return outputs
```

### Pattern B — subprocess

```python
"""MyTool adapter — calls tools/my_tool/run.py in its own venv."""
from typing import Any
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.cache import ToolCache
from app.tools.subprocess_runner import run_tool_subprocess

class MyToolAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec
        self._cache = ToolCache(tool_id="my_tool", tool_version=spec.version)

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        if not inputs.get("required_field"):
            raise ValueError("required_field is required")

        cached = self._cache.get(inputs)
        if cached is not None:
            await run_ctx.alog("Cache hit")
            return cached

        await run_ctx.alog("Starting via subprocess…")
        outputs = await run_tool_subprocess(
            tool_id="my_tool",
            inputs=inputs,
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,        # streams stderr live to terminal
            run_id=run_ctx.run_id,      # enables Stop Run button to kill the process
        )

        self._cache.put(inputs, outputs)
        return outputs
```

### Pattern C — HTTP

```python
"""MyTool adapter — calls the HTTP server at settings.mytool_url."""
from typing import Any
from app.config import settings
from app.models.tool_spec import ToolSpec
from app.tools.base import RunContext
from app.tools.http_tool import post_with_retry   # retries + health check + clear errors

class MyToolAdapter:
    def __init__(self, spec: ToolSpec) -> None:
        self.spec = spec

    async def invoke(self, inputs: dict[str, Any], run_ctx: RunContext) -> dict[str, Any]:
        await run_ctx.alog(f"Submitting to MyTool at {settings.mytool_url}")

        data = await post_with_retry(
            settings.mytool_url,
            "/predict",
            {"sequence": inputs["sequence"]},
            tool_name="MyTool",
            timeout=self.spec.runtime.timeout_seconds,
            on_log=run_ctx.alog,    # retry warnings appear in terminal
        )

        await run_ctx.alog("Done")
        return {"structure": data["pdb"], "scores": data.get("scores")}
```

`post_with_retry` (in `app/tools/http_tool.py`) does:
- `/health` ping before the real request — gives a clear "server not running at X" error instead of a raw ConnectError
- 3 retries with exponential backoff (2s → 4s → 8s) on connection errors and 5xx responses
- Extracts `detail` from error responses for readable messages
- Streams retry warnings through `on_log`

### Logging conventions

| Method | Use in | Effect |
|---|---|---|
| `run_ctx.log(msg)` | Pattern A (synchronous) | Appends to logs, writes to file |
| `await run_ctx.alog(msg)` | Patterns B & C (async) | Appends to logs, writes to file, **fires WS broadcast immediately** |

Every log line is also written to `/tmp/pdp-runs/<run_id>.log` — useful for debugging long-running tools (`tail -f /tmp/pdp-runs/<run_id>.log`).

### General adapter rules

- **Lazy imports** — import the tool inside `invoke()`, not at module top. Server starts even if the tool isn't installed.
- **`tempfile.TemporaryDirectory()`** — always use as context manager so files clean up on failure.
- **Input cleaning** — strip FASTA headers, whitespace, uppercase before passing to the tool.
- **Graceful fallback** — if an optional step fails (refinement, ANARCI pre-check), log a warning and continue.
- **Pad multi-model outputs** — always return all N keys, set unused to `None`:
  ```python
  for i in range(num_models + 1, 5):
      outputs[f"structure_{i}"] = None
  ```

---

## 6. Register the adapter

### `backend/app/workers/tasks.py`

```python
_ADAPTER_MAP = {
    ...
    "my_tool": ("app.tools.adapters.my_tool", "MyToolAdapter"),
}
```

### `backend/app/core/executor.py` — if the tool has analysis outputs

```python
_ANALYSIS_TOOLS = {"alphafold_monomer", "esmfold", "immunebuilder", "haddock3", "my_tool"}
```

Add the saving logic in `execute_run()`:
```python
elif node.tool == "my_tool":
    struct = outputs.get("structure")
    if struct:
        await _save_analysis(run.id, node_id, node.tool,
                             {"structure": struct, "plddt": outputs.get("confidence")})
```

---

## 7. Register tool outputs in the results database

Every tool that produces structures, docking results, sequences, or embeddings should write to the results DB via `backend/app/core/results_collector.py`. This is the canonical store — the Results page reads from here, not from run state.

**Step 1 — add to the right set:**
```python
_STRUCTURE_TOOLS = {"immunebuilder", "esmfold", "alphafold_monomer", "my_tool"}
_DESIGN_TOOLS    = {"proteinmpnn", "rfdiffusion", "my_tool"}
_EMBEDDING_TOOLS = {"abmap", "my_tool"}
```

**Step 2 — if the tool has a non-standard output format, add a handler:**
```python
async def _collect_my_tool(run, node_id, tool_id, inputs, outputs, molecule_id):
    async with AsyncSessionLocal() as db:
        db.add(StructureRow(
            molecule_id=molecule_id,
            run_id=run.id,
            node_id=node_id,
            tool_id=tool_id,
            pdb_data=outputs["structure"],
            confidence=json.dumps(outputs.get("confidence")),
        ))
        await db.commit()
```

**Step 3 — call it from `collect()`:**
```python
elif tool_id == "my_tool":
    await _collect_my_tool(run, node_id, tool_id, inputs, outputs, molecule_id)
```

The collector never crashes the pipeline — errors are logged and swallowed.

Schema reference:

| Table | Stores | Key link |
|---|---|---|
| `molecules` | One VH(+VL) sequence pair | root entity |
| `structures` | PDB from ImmuneBuilder / ESMFold / AlphaFold | → molecule_id |
| `docking_results` | HADDOCK3 best complex + CAPRI scores | → molecule_id |
| `design_sequences` | ProteinMPNN sequences / RFdiffusion backbones | → molecule_id |
| `embeddings` | AbMAP / ESM embedding metadata | → molecule_id |

---

## 8. Add the analysis visualization

### Structure output
`StructureViewer` in `AnalysisPanel.tsx` handles any PDB text out of the box.

### Confidence score
- `PLDDTChart.tsx` — per-residue 0–100 scores (reuse for pLDDT-style)
- `RMSDChart.tsx` — per-residue RMSD (ImmuneBuilder `error_estimates.npy`)
- `PAEHeatmap.tsx` — 2D matrix (AlphaFold PAE)

### `RunPanel.tsx` — add `hasAnalysis` check
```tsx
const hasAnalysis = nodeRun.status === "succeeded" && (
  nodeRun.outputs?.structure !== undefined ||
  nodeRun.outputs?.structure_1 !== undefined ||
  nodeRun.outputs?.my_output_key !== undefined   // ← add your key
);
```

---

## 9. Add the tool's paper to the Playground

Add an entry to `frontend/src/playground/papers.ts`:

```typescript
my_tool: {
  title: "Full paper title",
  authors: "LastName et al.",
  year: "2024",
  journal: "Nature / Science / bioRxiv",
  pdfUrl: "https://www.biorxiv.org/content/10.1101/xxx.full.pdf",  // open-access preferred
  abstractUrl: "https://doi.org/10.xxxx/...",
},
```

For local PDFs, place the file at `tools/<name>/PaperName.pdf` — the backend serves `tools/` as static files at `/papers/`:
```typescript
pdfUrl: "/papers/my_tool/PaperName.pdf",
```

Local PDFs render directly in the iframe (no Google Docs wrapper needed).

---

## 10. Frontend UX checklist

- [ ] Node has a working default → drag-drop + Run works with zero configuration
- [ ] Long-running tool: does the terminal show meaningful log lines? Add `_progress()` / `await run_ctx.alog()` at each major step
- [ ] For Pattern B subprocess tools: `run_id=run_ctx.run_id` passed to `run_tool_subprocess` so Stop Run can kill the process
- [ ] Outputs appear as blue dots in the ParamPanel after the run
- [ ] Large PDB outputs use `__artifact__` sentinel (automatic — outputs > 512 bytes are replaced in WS messages)
- [ ] "View Analysis" button appears in RunPanel after success
- [ ] Analysis panel shows the correct visualization for this tool's confidence metric
- [ ] Edge brightens blue during the run, turns green on success

---

## 11. Debugging checklist

**Backend won't start**
```bash
backend/.venv/bin/uvicorn app.main:app --reload
# Always use the venv uvicorn, not system uvicorn
```

**Tool not appearing in palette**
```bash
curl http://localhost:8000/api/tools | python3 -m json.tool | grep '"id"'
# If missing: check tool.yaml syntax; run backend with --reload and check startup logs
```

**Logs not appearing in terminal panel**
- Pattern A: use `run_ctx.log()` (synchronous) — but logs only appear at the end since there's no WS emit per line. Switch to `await run_ctx.alog()` if you want live updates.
- Pattern B: verify `_progress()` calls have `flush=True`. The runner uses `-u` and `PYTHONUNBUFFERED=1` but explicit flush is still the safest approach.
- Pattern C: verify the HTTP server is reachable — `http_tool.py` will log a health check failure clearly.
- Check the run log file: `tail -f /tmp/pdp-runs/<run_id>.log`

**HTTP tool: "server not reachable"**
- Verify the server is running: `curl http://localhost:800X/health`
- Check the URL in `.env` matches the port
- For conda-based servers: start with the correct `PATH` so CLI tools (e.g. ANARCI) are found
- NumPy 2.x / torch < 2.2 conflict → `pip install "numpy<2"` in the tool's env

**"X is only 0 residues" or empty input**
- Verify `default:` values are strings in `tool.yaml` (not YAML `null`)
- Check `defaultParams()` in `store.ts` — it filters out `__default_file__:` sentinels; large defaults are resolved server-side at execution time
- Test: drag node with no connections → Run

**"L chain not recognised" / ANARCI errors**
- Pre-validate with ANARCI before running the tool; add a fallback to nanobody mode
- Use kappa-chain test sequences (trastuzumab) as VL defaults, not lambda

**Edges don't brighten during the run**
- Check `runNodeStatuses` in Zustand store (React DevTools)
- WS messages must arrive — check browser devtools Network → WS tab

**Stop Run button doesn't appear**
- `run.status` must equal `"running"` in the frontend state
- The button only shows in `RunPanel.tsx` when `run?.status === "running"`

**Analysis panel shows nothing**
- Check `nodeRun.outputs` key matches what the adapter returns AND what `hasAnalysis` checks
- Query the analysis DB: `sqlite3 backend/protein_design.db "SELECT node_id, tool_id FROM node_analyses ORDER BY created_at DESC LIMIT 5;"`
- Check `GET /api/analysis/runs/{runId}/nodes/{nodeId}` returns data

---

## 12. Lessons learned (hard-won bugs & pitfalls)

These are real bugs we hit building the initial tool set. Read before writing code.

### Frontend / React

**`useRef(randomUUID())` is an anti-pattern for persistent IDs**

`useRef(randomUUID()).current` generates a new UUID on every component *mount*, not just once. On the Mac, hot-reloading and page refreshes mount fresh components — so every refresh silently creates a brand-new pipeline ID, and every Save creates a duplicate row in the DB.

Fix: store stable IDs in `useState` + `localStorage`:
```typescript
const [pipelineId, setPipelineId] = useState(() => {
  const stored = localStorage.getItem("pdp_pipeline_id");
  if (stored) return stored;
  const fresh = randomUUID();
  localStorage.setItem("pdp_pipeline_id", fresh);
  return fresh;
});
```
Also call `setPipelineId(pipeline.id)` when loading a saved pipeline, so subsequent Saves target the correct row.

---

**Vite HMR gets stuck if you add an import before the file exists**

If you add `import { Foo } from "./foo/Foo"` to a file and *then* create `foo/Foo.tsx`, Vite's HMR enters a broken state and serves stale bundles. The terminal shows no errors; the browser silently uses old code.

Fix order: **create the file first**, then add the import. If you already hit this state, kill the dev server (`lsof -ti tcp:5173 | xargs kill`) and restart it fresh.

---

**`savePipeline` fallback must only trigger on 404, not all errors**

The original catch-all pattern tried a POST after *any* PUT failure — masking real errors (permission denied, malformed JSON, etc.) with an unhelpful duplicate create.

```typescript
// WRONG — catches all errors
try { await api.put(...); } catch { await api.post(...); }

// RIGHT — only fall back on 404
try { await api.put(...); }
catch (err) {
  if ((err as { response?: { status?: number } })?.response?.status !== 404) throw err;
  await api.post(...);
}
```

---

### Backend / Python

**HTTP 400 from a tool server kills the entire pipeline**

`post_with_retry` retries on connection errors and 5xx responses, but treats 4xx as fatal (they mean "your request is malformed"). If an optional/enrichment tool like AbMAP rejects a sequence with `400 Region seems invalid`, the `RuntimeError` it raises propagates up and cancels the run.

Fix: wrap optional tools in `try/except RuntimeError` in the adapter and return a graceful empty result:
```python
try:
    data = await post_with_retry(settings.abmap_url, "/embed", payload, ...)
except RuntimeError as exc:
    await run_ctx.alog(f"⚠ AbMAP skipped: {exc}")
    return {"embedding": [], "metadata": {"error": str(exc), "skipped": True}}
```
Apply this pattern to any tool whose output is not required by downstream nodes.

---

**Subprocess adapters must use asyncio — `subprocess.Popen` blocks the event loop**

`subprocess.Popen` with `for line in proc.stdout:` is a *blocking* loop that freezes the FastAPI event loop for the entire duration of the tool run (minutes). All other WebSocket updates and API requests stall.

Always use `asyncio.create_subprocess_exec` or the `run_tool_subprocess` helper instead:
```python
# WRONG
proc = subprocess.Popen(cmd, ...)
for line in proc.stdout:          # ← blocks the event loop
    await run_ctx.alog(line)

# RIGHT — use run_tool_subprocess (handles async + streaming + cancellation)
outputs = await run_tool_subprocess(
    tool_id="my_tool", inputs=inputs, timeout=..., on_log=run_ctx.alog, run_id=run_ctx.run_id
)
```

---

### Frontend UX — live terminal

**"Waiting for output" shows the wrong node during transitions**

When one node finishes and the next starts, the running node typically has no logs for 10–30 seconds (model loading, environment init). If the terminal switches immediately to the running node, it shows blank — users think the tool crashed.

Fix in `TerminalLog`:
1. Track the currently-running node and the last *finished* node
2. When the running node has no logs yet, display the last finished node's output at reduced opacity with a "↑ last output · waiting for {running node}…" footer
3. Switch to the running node's logs as soon as its first line arrives

```typescript
const showContext = isRunning && runningLines.length === 0 && !!lastNode;
// render: showContext ? lastNode's lines (opacity-40) : runningLines
```

---

**NumPy 2.x breaks PyTorch < 2.2 silently**

Any tool using `torch < 2.2` will fail with cryptic import errors (`ImportError: numpy.core._multiarray_umath`) if NumPy ≥ 2.0 is installed. Always pin `numpy<2` when installing tools that use older torch versions.

---

## 13. Shipping checklist

```
[ ] tool.yaml has working defaults (drag-drop → Run works immediately)
[ ] Large defaults use default_file: not default: (keeps API payload small)
[ ] Lazy imports inside invoke()
[ ] run_ctx.log() / await run_ctx.alog() at start, each major step, end
[ ] Pattern B: run_id=run_ctx.run_id passed to run_tool_subprocess
[ ] Multi-output tools pad unused slots with None
[ ] Adapter registered in tasks.py _ADAPTER_MAP
[ ] Analysis saving added to executor.py if tool outputs structure/confidence
[ ] Tool outputs registered in results_collector.py
[ ] hasAnalysis check updated in RunPanel.tsx
[ ] Paper added to playground/papers.ts
[ ] Test: drag node with no connections → Run → succeeds with defaults
[ ] Test: connect sequence_input → new_tool → Run → succeeds
[ ] TypeScript compiles: cd frontend && npx tsc --noEmit
[ ] Backend starts cleanly: backend/.venv/bin/uvicorn app.main:app --reload
```
