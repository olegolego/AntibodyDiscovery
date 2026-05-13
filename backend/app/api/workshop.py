"""Workshop API — create, test, benchmark, and publish custom tools."""
import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic as _anthropic
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import BenchmarkRow, CustomToolRow, DatasetEntryRow
from app.db.session import AsyncSessionLocal
from app.models.tool_spec import ToolSpec
from app.tools.registry import tool_registry
from app.workers import tasks as _tasks

router = APIRouter()
ws_router = APIRouter()

_MODEL = "claude-sonnet-4-6"
_TOOLS_DIR = Path(__file__).resolve().parents[4] / "tools"

# ── Default templates ─────────────────────────────────────────────────────────

DEFAULT_YAML = """\
id: my_tool
name: My Tool
version: "1.0"
category: utility
description: ""
inputs:
  - name: input_data
    type: json
    required: true
outputs:
  - name: result
    type: json
runtime:
  kind: local_python
  timeout_seconds: 120
  gpu: false
"""

DEFAULT_RUN_PY = '''\
import json
import sys


def run(inputs: dict) -> dict:
    # your logic here
    return {"result": inputs}


if __name__ == "__main__":
    inputs = json.load(sys.stdin)
    try:
        out = run(inputs)
    except Exception as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.stdout.flush()
        sys.exit(1)
    json.dump(out, sys.stdout)
    sys.stdout.flush()
'''

# ── Pydantic request/response models ─────────────────────────────────────────

class CreateToolRequest(BaseModel):
    name: str
    tool_yaml: str = DEFAULT_YAML
    run_py: str = DEFAULT_RUN_PY
    requirements: str | None = None


class UpdateToolRequest(BaseModel):
    name: str | None = None
    tool_yaml: str | None = None
    run_py: str | None = None
    requirements: str | None = None


class CustomToolOut(BaseModel):
    id: str
    name: str
    tool_yaml: str
    run_py: str
    requirements: str | None
    status: str
    created_at: str
    updated_at: str


class ClaudeRequest(BaseModel):
    prompt: str
    context: str = ""   # current run.py or error output for context


# ── Helpers ───────────────────────────────────────────────────────────────────

def _row_to_out(row: CustomToolRow) -> CustomToolOut:
    return CustomToolOut(
        id=row.id,
        name=row.name,
        tool_yaml=row.tool_yaml,
        run_py=row.run_py,
        requirements=row.requirements,
        status=row.status,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


async def _run_script(
    run_py: Path,
    inputs: dict[str, Any],
    timeout: int = 120,
    on_log: Any | None = None,
) -> dict[str, Any]:
    """Execute a run.py directly (no tool venv needed — uses backend Python)."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", str(run_py),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PYTHONUNBUFFERED": "1", **os.environ},
    )
    stdin_bytes = json.dumps(inputs).encode()
    proc.stdin.write(stdin_bytes)
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_lines: list[str] = []

    async def _drain_stderr() -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            line = raw.decode().rstrip()
            if line:
                stderr_lines.append(line)
                if on_log:
                    await on_log(line)

    try:
        stdout_data, _ = await asyncio.wait_for(
            asyncio.gather(proc.stdout.read(), _drain_stderr()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"Timed out after {timeout}s")

    await proc.wait()

    if proc.returncode != 0:
        err = "\n".join(stderr_lines[-20:]) or stdout_data.decode()[:500]
        raise RuntimeError(f"Exited {proc.returncode}: {err}")

    try:
        return json.loads(stdout_data)
    except json.JSONDecodeError:
        return {"raw_output": stdout_data.decode()[:2000]}


def _compute_metric(
    metric: str,
    predicted: Any,
    expected: Any,
    metric_fn: str | None,
) -> float | None:
    if predicted is None or expected is None:
        return None
    if metric == "sequence_recovery":
        p, e = str(predicted).upper(), str(expected).upper()
        return sum(a == b for a, b in zip(p, e)) / len(e) if e else None
    if metric == "pearson":
        try:
            from scipy.stats import pearsonr  # type: ignore
            return float(pearsonr([float(predicted)], [float(expected)])[0])
        except Exception:
            return None
    if metric == "rmsd":
        try:
            return float(predicted)
        except Exception:
            return None
    if metric == "custom" and metric_fn:
        ns: dict = {}
        try:
            exec(metric_fn, ns)  # noqa: S102
            fn = ns.get("score_fn")
            if callable(fn):
                return float(fn(predicted, expected))
        except Exception:
            pass
    return None


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/tools")
async def list_tools() -> list[dict]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CustomToolRow).order_by(CustomToolRow.updated_at.desc())
            )
        ).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/tools", status_code=201)
async def create_tool(body: CreateToolRequest) -> CustomToolOut:
    async with AsyncSessionLocal() as db:
        row = CustomToolRow(
            name=body.name,
            tool_yaml=body.tool_yaml,
            run_py=body.run_py,
            requirements=body.requirements,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _row_to_out(row)


@router.get("/tools/{tool_id}")
async def get_tool(tool_id: str) -> CustomToolOut:
    async with AsyncSessionLocal() as db:
        row = await db.get(CustomToolRow, tool_id)
    if not row:
        raise HTTPException(status_code=404, detail="Tool not found")
    return _row_to_out(row)


@router.put("/tools/{tool_id}")
async def update_tool(tool_id: str, body: UpdateToolRequest) -> CustomToolOut:
    async with AsyncSessionLocal() as db:
        row = await db.get(CustomToolRow, tool_id)
        if not row:
            raise HTTPException(status_code=404, detail="Tool not found")
        if body.name is not None:
            row.name = body.name
        if body.tool_yaml is not None:
            row.tool_yaml = body.tool_yaml
        if body.run_py is not None:
            row.run_py = body.run_py
        if body.requirements is not None:
            row.requirements = body.requirements
        row.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(row)
    return _row_to_out(row)


@router.delete("/tools/{tool_id}", status_code=204)
async def delete_tool(tool_id: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(CustomToolRow, tool_id)
        if not row:
            raise HTTPException(status_code=404, detail="Tool not found")
        if row.status == "published":
            raise HTTPException(status_code=400, detail="Cannot delete a published tool")
        await db.delete(row)
        await db.commit()


# ── Publish ───────────────────────────────────────────────────────────────────

@router.post("/tools/{tool_id}/publish")
async def publish_tool(tool_id: str) -> dict:
    import yaml as _yaml

    async with AsyncSessionLocal() as db:
        row = await db.get(CustomToolRow, tool_id)
        if not row:
            raise HTTPException(status_code=404, detail="Tool not found")

        try:
            data = _yaml.safe_load(row.tool_yaml)
            spec = ToolSpec.model_validate(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid tool.yaml: {exc}")

        dest = _TOOLS_DIR / f"custom_{tool_id}"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "tool.yaml").write_text(row.tool_yaml)
        (dest / "run.py").write_text(row.run_py)
        if row.requirements:
            (dest / "requirements.txt").write_text(row.requirements)

        tool_registry.reload()

        # Register adapter at runtime so the pipeline executor can dispatch it
        _tasks._ADAPTER_MAP[f"custom_{tool_id}"] = (
            "app.tools.adapters.custom_tool",
            "CustomToolAdapter",
        )

        row.status = "published"
        row.updated_at = datetime.utcnow()
        await db.commit()

    return {"tool_id": f"custom_{tool_id}", "spec": spec.model_dump()}


# ── Claude code help ──────────────────────────────────────────────────────────

_WORKSHOP_SYSTEM = """\
You are an expert Python developer helping a user write a bioinformatics tool for an
antibody design pipeline. Every tool follows this exact pattern:

  import json, sys

  def run(inputs: dict) -> dict:
      # logic here — all inputs are in the dict
      return {"result": ...}   # or any output keys matching tool.yaml outputs

  if __name__ == "__main__":
      inputs = json.load(sys.stdin)
      try:
          out = run(inputs)
      except Exception as e:
          json.dump({"error": str(e)}, sys.stdout); sys.stdout.flush(); sys.exit(1)
      json.dump(out, sys.stdout); sys.stdout.flush()

Standard library, numpy, scipy, and biopython are available.
Return ONLY valid Python code — no markdown fences, no explanation."""


@router.post("/tools/{tool_id}/claude")
async def claude_code_help(tool_id: str, body: ClaudeRequest) -> dict[str, str]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not set")

    user_content = body.prompt
    if body.context:
        user_content = f"Current code:\n```python\n{body.context}\n```\n\n{body.prompt}"

    client = _anthropic.AsyncAnthropic(api_key=api_key)
    try:
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=2048,
            system=[{
                "type": "text",
                "text": _WORKSHOP_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
        )
    except _anthropic.APIError as exc:
        raise HTTPException(status_code=502, detail=f"Anthropic API error: {exc}")

    text = message.content[0].text
    fenced = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    code = fenced.group(1).strip() if fenced else text.strip()
    return {"code": code}


# ── Benchmarks ────────────────────────────────────────────────────────────────

@router.get("/benchmarks")
async def list_benchmarks() -> list[dict]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(BenchmarkRow).order_by(BenchmarkRow.name))
        ).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "metric": r.metric,
            "pass_threshold": json.loads(r.pass_threshold) if r.pass_threshold else None,
        }
        for r in rows
    ]


@router.post("/tools/{tool_id}/benchmark/{benchmark_id}")
async def run_benchmark(tool_id: str, benchmark_id: str) -> dict:
    async with AsyncSessionLocal() as db:
        tool = await db.get(CustomToolRow, tool_id)
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        bench = await db.get(BenchmarkRow, benchmark_id)
        if not bench:
            raise HTTPException(status_code=404, detail="Benchmark not found")
        entries = (
            await db.execute(
                select(DatasetEntryRow).where(
                    DatasetEntryRow.dataset_id == bench.dataset_id
                )
            )
        ).scalars().all()

    input_cols: list[str] = json.loads(bench.input_columns)
    per_entry = []

    with tempfile.TemporaryDirectory() as tmpdir:
        run_py_path = Path(tmpdir) / "run.py"
        run_py_path.write_text(tool.run_py)

        for entry in entries:
            entry_data: dict = json.loads(entry.data or "{}")
            inputs: dict[str, Any] = {}
            for col in input_cols:
                if col == "heavy_chain":
                    inputs[col] = entry.heavy_chain or ""
                elif col == "light_chain":
                    inputs[col] = entry.light_chain or ""
                elif col == "name":
                    inputs[col] = entry.name or ""
                else:
                    inputs[col] = entry_data.get(col)

            expected = entry_data.get(bench.expected_column)

            try:
                result = await _run_script(run_py_path, inputs, timeout=120)
                predicted = result.get("result")
                score = _compute_metric(bench.metric, predicted, expected, bench.metric_fn)
                per_entry.append({
                    "entry_id": entry.id,
                    "name": entry.name,
                    "predicted": predicted,
                    "expected": expected,
                    "score": score,
                    "error": None,
                })
            except Exception as exc:
                per_entry.append({
                    "entry_id": entry.id,
                    "name": entry.name,
                    "predicted": None,
                    "expected": expected,
                    "score": None,
                    "error": str(exc),
                })

    scores = [e["score"] for e in per_entry if e["score"] is not None]
    mean_score = sum(scores) / len(scores) if scores else None
    threshold = json.loads(bench.pass_threshold) if bench.pass_threshold else None

    # Lower is better for rmsd; higher is better for everything else
    if threshold is not None and mean_score is not None:
        passed = mean_score <= threshold if bench.metric == "rmsd" else mean_score >= threshold
    else:
        passed = None

    return {
        "benchmark_id": benchmark_id,
        "metric": bench.metric,
        "mean_score": mean_score,
        "pass_threshold": threshold,
        "passed": passed,
        "n_entries": len(entries),
        "n_errors": sum(1 for e in per_entry if e["error"]),
        "per_entry": per_entry,
    }


# ── Dataset batch run ────────────────────────────────────────────────────────

@router.post("/tools/{tool_id}/run-dataset/{dataset_id}")
async def run_on_dataset(tool_id: str, dataset_id: str) -> dict:
    """Run the tool on every entry in a dataset. Returns per-entry outputs."""
    async with AsyncSessionLocal() as db:
        tool = await db.get(CustomToolRow, tool_id)
        if not tool:
            raise HTTPException(status_code=404, detail="Tool not found")
        entries = (
            await db.execute(
                select(DatasetEntryRow).where(DatasetEntryRow.dataset_id == dataset_id)
            )
        ).scalars().all()

    if not entries:
        return {"dataset_id": dataset_id, "n_entries": 0, "results": []}

    results = []
    with tempfile.TemporaryDirectory() as tmpdir:
        run_py_path = Path(tmpdir) / "run.py"
        run_py_path.write_text(tool.run_py)

        for entry in entries:
            entry_data: dict = json.loads(entry.data or "{}")
            inputs: dict[str, Any] = {
                "name": entry.name,
                "heavy_chain": entry.heavy_chain,
                "light_chain": entry.light_chain,
                **entry_data,
            }
            # Remove None values so tool doesn't get unexpected nulls
            inputs = {k: v for k, v in inputs.items() if v is not None}

            try:
                out = await _run_script(run_py_path, inputs, timeout=120)
                results.append({
                    "entry_id": entry.id,
                    "name": entry.name,
                    "inputs": inputs,
                    "result": out,
                    "error": None,
                })
            except Exception as exc:
                results.append({
                    "entry_id": entry.id,
                    "name": entry.name,
                    "inputs": inputs,
                    "result": None,
                    "error": str(exc),
                })

    return {
        "dataset_id": dataset_id,
        "n_entries": len(entries),
        "n_errors": sum(1 for r in results if r["error"]),
        "results": results,
    }


# ── WebSocket: live tool execution ────────────────────────────────────────────

@ws_router.websocket("/ws/workshop/{session_id}")
async def workshop_execute(ws: WebSocket, session_id: str) -> None:
    """
    Protocol:
      client → {"run_py": str, "inputs": {...}}
      server → {"type": "log",  "text": str}
               {"type": "done", "result": any, "error": str|null}
               {"type": "error", "message": str}
    """
    await ws.accept()
    try:
        raw = await ws.receive_text()
        payload = json.loads(raw)
        run_py_code = str(payload.get("run_py", ""))
        inputs = dict(payload.get("inputs", {}))

        if not run_py_code.strip():
            await ws.send_json({"type": "done", "result": None, "error": "Empty run.py"})
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            run_py_path = Path(tmpdir) / "run.py"
            run_py_path.write_text(run_py_code)
            await _stream_execution(run_py_path, inputs, ws, timeout=120)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass


async def _stream_execution(
    run_py: Path,
    inputs: dict[str, Any],
    ws: WebSocket,
    timeout: int = 120,
) -> None:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-u", str(run_py),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PYTHONUNBUFFERED": "1", **os.environ},
    )
    proc.stdin.write(json.dumps(inputs).encode())
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_lines: list[str] = []

    async def _drain_stderr() -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            line = raw.decode().rstrip()
            if line:
                stderr_lines.append(line)
                try:
                    await ws.send_json({"type": "log", "text": line})
                except Exception:
                    pass

    try:
        stdout_data, _ = await asyncio.wait_for(
            asyncio.gather(proc.stdout.read(), _drain_stderr()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        await ws.send_json({"type": "done", "result": None, "error": f"Timed out after {timeout}s"})
        try:
            await ws.close()
        except Exception:
            pass
        return

    await proc.wait()

    if proc.returncode != 0:
        err = "\n".join(stderr_lines[-10:]) or stdout_data.decode()[:500]
        await ws.send_json({"type": "done", "result": None, "error": err})
        try:
            await ws.close()
        except Exception:
            pass
        return

    try:
        result = json.loads(stdout_data)
    except json.JSONDecodeError:
        result = {"raw_output": stdout_data.decode()[:2000]}

    await ws.send_json({"type": "done", "result": result, "error": None})
    try:
        await ws.close()
    except Exception:
        pass
