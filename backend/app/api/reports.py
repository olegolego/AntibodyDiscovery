"""Bug-report & feedback inbox.

Two entry points from the UI:

  * ``POST /api/reports/feedback``  — general free-text feedback.
  * ``POST /api/reports/run-bug``   — "this run misbehaved"; the backend pulls the
    run, *distills* a compact diagnostic bundle (failed node, error, log tail,
    tool params, and *summarized* upstream input shapes — never the raw
    megabyte blobs) and renders a ready-to-read markdown ``summary``.

Reports are written as timestamped JSON files into an inbox directory
(``PDP_REPORTS_DIR``, default ``<repo>/bug_reports``). A Claude Code session can
then read the latest file and fix the bug directly — the distillation keeps the
context small so no tokens are wasted re-deriving what already failed.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.executor import get_run
from app.models.run import Run

router = APIRouter()

_REPO_DIR = Path(__file__).resolve().parents[3]
_AUTOFIX_SCRIPT = _REPO_DIR / "scripts" / "auto_fix.sh"
# Kill-switch: set PDP_AUTOFIX_ENABLED=0 to disable autonomous fixing entirely.
_AUTOFIX_ENABLED = os.getenv("PDP_AUTOFIX_ENABLED", "1") != "0"

# Inbox dir — default to <repo_root>/bug_reports (reports.py lives at
# backend/app/api/reports.py, so parents[3] is the repo root).
_REPORTS_DIR = Path(
    os.getenv("PDP_REPORTS_DIR", str(Path(__file__).resolve().parents[3] / "bug_reports"))
)
_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Mirror of the executor's per-run log file location (see app/tools/base.py).
_RUN_LOG_DIR = Path(os.getenv("PDP_RUN_LOG_DIR", "/tmp/pdp-runs"))

_MAX_LOG_LINES = 40        # per-node log tail kept in the bundle
_MAX_RUNLOG_LINES = 60     # combined run-log tail kept in the bundle
_MAX_ERROR_CHARS = 4000    # error/traceback truncation
_STR_PREVIEW = 100         # long strings collapsed to <str len=N> preview


# ── Request models ──────────────────────────────────────────────────────────


class FeedbackRequest(BaseModel):
    message: str
    email: str | None = None
    category: str = "feedback"  # feedback | idea | bug | other
    context: dict[str, Any] | None = None  # optional free-form (e.g. current page)


class RunBugRequest(BaseModel):
    run_id: str
    message: str | None = None
    email: str | None = None
    auto_fix: bool = False  # if true, spawn the autonomous fix-and-deploy worker


# ── Distillation helpers ──────────────────────────────────────────────────────


def _summarize_value(value: Any, depth: int = 0) -> Any:
    """Collapse a value into a compact, token-cheap descriptor.

    PDB/FASTA/embedding payloads can be megabytes; we never want those verbatim
    in a bug report. Scalars pass through; long strings, lists and nested dicts
    become shape descriptors.
    """
    if value is None or isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _STR_PREVIEW:
            return value
        return f"<str len={len(value)}> {value[:_STR_PREVIEW]}…"
    if isinstance(value, list):
        n = len(value)
        if n == 0:
            return []
        return f"<list n={n}> e.g. {_summarize_value(value[0], depth + 1)!r}"
    if isinstance(value, dict):
        if depth >= 2:
            return f"<dict keys={list(value.keys())}>"
        return {k: _summarize_value(v, depth + 1) for k, v in value.items()}
    return f"<{type(value).__name__}>"


def _upstream_node_ids(snapshot: dict, node_id: str) -> list[str]:
    """Node IDs whose outputs feed ``node_id`` (edge format ``<node>.<port>``)."""
    ups: list[str] = []
    for edge in snapshot.get("edges", []):
        target = str(edge.get("target", ""))
        if target.split(".", 1)[0] == node_id:
            src = str(edge.get("source", "")).split(".", 1)[0]
            if src and src not in ups:
                ups.append(src)
    return ups


def _read_runlog_tail(run_id: str) -> list[str]:
    path = _RUN_LOG_DIR / f"{run_id}.log"
    try:
        lines = path.read_text(errors="replace").splitlines()
        return lines[-_MAX_RUNLOG_LINES:]
    except Exception:
        return []


def _distill_run(run: Run) -> dict[str, Any]:
    snapshot = run.pipeline_snapshot or {}
    tool_map = {n["id"]: n.get("tool", "unknown") for n in snapshot.get("nodes", [])}
    params_map = {n["id"]: n.get("params", {}) for n in snapshot.get("nodes", [])}

    run_status = run.status.value if hasattr(run.status, "value") else str(run.status)

    node_summaries: list[dict] = []
    failed_nodes: list[dict] = []
    for node_id, nr in run.nodes.items():
        st = nr.status.value if hasattr(nr.status, "value") else str(nr.status)
        node_summaries.append(
            {"node_id": node_id, "tool": tool_map.get(node_id, "unknown"), "status": st}
        )
        if st == "failed":
            inputs: dict[str, Any] = {}
            for up in _upstream_node_ids(snapshot, node_id):
                up_run = run.nodes.get(up)
                if up_run and up_run.outputs:
                    inputs[up] = {
                        "tool": tool_map.get(up, "unknown"),
                        "outputs": _summarize_value(dict(up_run.outputs), depth=1),
                    }
            failed_nodes.append(
                {
                    "node_id": node_id,
                    "tool": tool_map.get(node_id, "unknown"),
                    "params": _summarize_value(dict(params_map.get(node_id, {})), depth=1),
                    "error": (nr.error or "")[:_MAX_ERROR_CHARS],
                    "logs_tail": list(nr.logs or [])[-_MAX_LOG_LINES:],
                    "upstream_inputs": inputs,
                }
            )

    return {
        "run_id": run.id,
        "pipeline_id": run.pipeline_id,
        "pipeline_name": str(snapshot.get("name", "Untitled pipeline")),
        "status": run_status,
        "created_at": run.created_at,
        "loop_id": run.loop_id,
        "iteration": run.iteration,
        "nodes": node_summaries,
        "failed_nodes": failed_nodes,
        "run_log_tail": _read_runlog_tail(run.id),
    }


def _render_summary(distilled: dict[str, Any], message: str | None, email: str | None) -> str:
    """Human/LLM-readable markdown — the thing a Claude session reads to fix the bug."""
    lines: list[str] = []
    lines.append(f"# Bug report — {distilled['pipeline_name']}")
    lines.append("")
    lines.append(
        f"**Run:** `{distilled['run_id']}`  •  **Status:** {distilled['status']}  "
        f"•  **Created:** {distilled.get('created_at') or '—'}"
    )
    if distilled.get("loop_id"):
        lines.append(f"**Loop:** `{distilled['loop_id']}` (iteration {distilled.get('iteration')})")
    if email:
        lines.append(f"**Reporter:** {email}")
    lines.append("")

    lines.append("## What the user said")
    lines.append(message.strip() if message and message.strip() else "_(no message provided)_")
    lines.append("")

    lines.append("## Pipeline nodes")
    for n in distilled["nodes"]:
        mark = "❌" if n["status"] == "failed" else ("✅" if n["status"] == "succeeded" else "•")
        lines.append(f"- {mark} `{n['node_id']}` [{n['tool']}] — {n['status']}")
    lines.append("")

    if distilled["failed_nodes"]:
        for fn in distilled["failed_nodes"]:
            lines.append(f"## Failed node: `{fn['node_id']}` ({fn['tool']})")
            lines.append("")
            lines.append(f"**Params:** `{json.dumps(fn['params'], default=str)}`")
            lines.append("")
            lines.append("**Error:**")
            lines.append("```")
            lines.append(fn["error"] or "(no error text captured)")
            lines.append("```")
            if fn["logs_tail"]:
                lines.append("**Last log lines:**")
                lines.append("```")
                lines.extend(fn["logs_tail"])
                lines.append("```")
            if fn["upstream_inputs"]:
                lines.append("**Upstream inputs (summarized):**")
                for up, info in fn["upstream_inputs"].items():
                    lines.append(f"- `{up}` [{info['tool']}]: `{json.dumps(info['outputs'], default=str)}`")
            lines.append("")
    else:
        lines.append("## No failed nodes")
        lines.append(
            "_The run had no node in `failed` state — the user is reporting "
            "unexpected behaviour rather than a hard crash. See the run-log tail below._"
        )
        lines.append("")
        if distilled["run_log_tail"]:
            lines.append("**Run log tail:**")
            lines.append("```")
            lines.extend(distilled["run_log_tail"])
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def _safe_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")


def _write_report(record: dict[str, Any], kind: str, suffix: str = "") -> str:
    suffix = re.sub(r"[^A-Za-z0-9_-]", "", suffix)[:16]
    name = f"{_safe_stamp()}_{kind}" + (f"_{suffix}" if suffix else "") + ".json"
    path = _REPORTS_DIR / name
    path.write_text(json.dumps(record, indent=2, default=str))
    return name


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/feedback", status_code=201)
async def submit_feedback(req: FeedbackRequest):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is required")
    record = {
        "type": "feedback",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reporter_email": req.email,
        "category": req.category,
        "message": req.message.strip(),
        "context": req.context or {},
    }
    saved = _write_report(record, "feedback", req.category)
    return {"saved": saved}


@router.post("/run-bug", status_code=201)
async def report_run_bug(req: RunBugRequest):
    run = await get_run(req.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    distilled = _distill_run(run)
    summary = _render_summary(distilled, req.message, req.email)
    record = {
        "type": "run-bug",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reporter_email": req.email,
        "user_message": (req.message or "").strip() or None,
        "run_id": run.id,
        "pipeline_name": distilled["pipeline_name"],
        "context": distilled,
        "summary": summary,
    }
    saved = _write_report(record, "run-bug", run.id.replace("-", "")[:8])

    autofix_started = False
    autofix_error: str | None = None
    if req.auto_fix:
        if not _AUTOFIX_ENABLED:
            autofix_error = "Autonomous fixing is disabled (PDP_AUTOFIX_ENABLED=0)."
        elif not _AUTOFIX_SCRIPT.exists():
            autofix_error = f"Worker script not found: {_AUTOFIX_SCRIPT}"
        else:
            try:
                _spawn_autofix(_REPORTS_DIR / saved)
                autofix_started = True
            except Exception as exc:  # pragma: no cover - defensive
                autofix_error = f"Failed to start fixer: {exc}"

    return {
        "saved": saved,
        "summary": summary,
        "autofix_started": autofix_started,
        "autofix_error": autofix_error,
    }


def _spawn_autofix(report_path: Path) -> None:
    """Launch the fix-and-deploy worker fully detached.

    start_new_session=True puts the worker in its own session/process group so
    that when the worker restarts the backend (killing the uvicorn process), the
    worker itself survives to finish deploying / rolling back.
    """
    subprocess.Popen(
        ["bash", str(_AUTOFIX_SCRIPT), str(report_path)],
        cwd=str(_REPO_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


@router.get("/autofix/{report_file}")
async def get_autofix_status(report_file: str) -> dict[str, Any]:
    """Poll the status of an autonomous fix run, keyed by its report filename."""
    # Guard against path traversal — only a bare filename in the inbox is allowed.
    name = Path(report_file).name
    status_path = _REPORTS_DIR / f"{name[:-5] if name.endswith('.json') else name}.autofix.json"
    if not status_path.exists():
        return {"phase": "pending", "message": "Fixer has not reported yet."}
    try:
        return json.loads(status_path.read_text())
    except Exception:
        return {"phase": "pending", "message": "Status not readable yet."}


@router.get("/")
async def list_reports():
    """List filed reports (most recent first) with light metadata."""
    out: list[dict] = []
    for path in sorted(_REPORTS_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        msg = data.get("user_message") or data.get("message") or ""
        out.append(
            {
                "file": path.name,
                "type": data.get("type"),
                "created_at": data.get("created_at"),
                "run_id": data.get("run_id"),
                "pipeline_name": data.get("pipeline_name"),
                "message_preview": (msg[:140] if isinstance(msg, str) else ""),
            }
        )
    return out
