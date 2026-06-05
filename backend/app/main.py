import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env so ANTHROPIC_API_KEY and other secrets are available
# regardless of how the process is launched.
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api import analysis, artifacts, compute, datasets, loop_runs, md_ground, md_ground_ws, ml_analysis, pipelines, reports, results, runs, sequences, tools, trained_models, workshop, ws
from app.config import settings
from app.db.models import Base, CustomToolRow, LoopRunRow, RunRow
from app.db.session import AsyncSessionLocal, engine
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)
_TOOLS_DIR = Path(__file__).parent.parent.parent / "tools"


async def _migrate(conn) -> None:
    """Add columns introduced after initial schema creation."""
    await conn.run_sync(Base.metadata.create_all)
    _sa = __import__("sqlalchemy")
    for table, col in [
        ("docking_results", "tool_id TEXT"),
        ("docking_results", "extra_data TEXT"),
        ("runs", "loop_id TEXT"),
        ("runs", "iteration INTEGER"),
        ("loop_runs", "loop_history TEXT"),
    ]:
        try:
            await conn.execute(_sa.text(f"ALTER TABLE {table} ADD COLUMN {col}"))
        except Exception:
            pass  # column already exists

    # Indexes added post-launch (CREATE INDEX IF NOT EXISTS is idempotent)
    for ddl in [
        "CREATE INDEX IF NOT EXISTS ix_runs_created_at ON runs (created_at)",
    ]:
        await conn.execute(_sa.text(ddl))


def _kill_orphaned_haddock() -> None:
    """Kill leftover HADDOCK/CNS processes from a previous server session.

    Called at startup before _mark_orphaned_runs so that processes spawned by
    interrupted runs don't survive as orphans when new HADDOCK nodes are retried.
    """
    import signal
    import subprocess
    patterns = [
        "haddock3/run.py",
        "haddock3/.venv/bin/haddock3",
        "haddock/cns/bin/arm64-darwin.bin",
    ]
    killed = 0
    for pattern in patterns:
        try:
            result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
            pids = [int(p) for p in result.stdout.strip().split() if p.isdigit()]
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed += 1
                except ProcessLookupError:
                    pass
                except Exception:
                    pass
        except Exception:
            pass
    if killed:
        logger.warning("Killed %d orphaned HADDOCK/CNS process(es) from previous session", killed)

    # Clean up orphaned HADDOCK temp directories (identified by docking.cfg inside).
    # These accumulate when processes are SIGKILL'd and TemporaryDirectory.__del__ doesn't run.
    import shutil
    import tempfile
    tmp_root = Path(tempfile.gettempdir())
    cleaned = 0
    for cfg in tmp_root.glob("*/docking.cfg"):
        try:
            shutil.rmtree(cfg.parent, ignore_errors=True)
            cleaned += 1
        except Exception:
            pass
    if cleaned:
        logger.info("Cleaned %d orphaned HADDOCK temp dir(s)", cleaned)


async def _mark_orphaned_runs() -> None:
    """Mark any runs left in running/queued as failed — they were interrupted by a server restart."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(RunRow).where(RunRow.status.in_(["running", "queued"]))
            )
        ).scalars().all()
        if not rows:
            return
        for row in rows:
            try:
                data = json.loads(row.data)
                data["status"] = "failed"
                for node in data.get("nodes", {}).values():
                    if node.get("status") in ("running", "queued", "pending"):
                        node["status"] = "failed"
                        node["error"] = "Interrupted by server restart"
                row.status = "failed"
                row.data = json.dumps(data)
                row.updated_at = datetime.utcnow()
            except Exception:
                row.status = "failed"
                row.updated_at = datetime.utcnow()
        await db.commit()
        logger.warning("Marked %d orphaned run(s) as failed (server restart)", len(rows))


async def _resume_interrupted_loops() -> None:
    """After a restart, re-queue the next iteration for any loop whose latest run was orphaned.

    The orphan-marking pass already set those runs to 'failed'. Here we check if any
    loop is still in status='running' and try to continue it from where it left off.
    """
    import asyncio
    from app.core.executor import create_run, execute_run
    from app.core.loop_executor import _extract_next_sequence, _patch_pipeline, _save_loop
    from app.models.pipeline import Pipeline
    from app.models.run import Run

    async with AsyncSessionLocal() as db:
        loop_rows = (await db.execute(select(LoopRunRow).where(LoopRunRow.status == "running"))).scalars().all()
        if not loop_rows:
            return

    for loop_row in loop_rows:
        try:
            run_ids: list[str] = json.loads(loop_row.run_ids or "[]")
            if not run_ids:
                continue
            latest_run_id = run_ids[-1]
            iteration = loop_row.current_iteration or 0
            max_iterations = loop_row.max_iterations or 5

            async with AsyncSessionLocal() as db:
                run_row = await db.get(RunRow, latest_run_id)
                if run_row is None or run_row.status != "failed":
                    continue  # still running or succeeded normally — skip

            # The latest run was interrupted. Re-build next iteration.
            pipeline_data = json.loads(loop_row.pipeline_snapshot or "{}")
            pipeline = Pipeline.model_validate(pipeline_data)

            if iteration + 1 >= max_iterations:
                await _save_loop(loop_row.id, "succeeded", "max_iterations", iteration + 1, run_ids)
                logger.info("Loop %s completed at restart recovery", loop_row.id)
                continue

            loop_history = json.loads(loop_row.loop_history or "[]")
            # Try to extract the next sequence from the interrupted run (loop_end may have run).
            run_data = json.loads(run_row.data or "{}")
            run = Run.model_validate(run_data)
            next_vh, next_vl = _extract_next_sequence(run)

            # Fallback: if loop_end didn't complete in the failed run, look backward through
            # prior successful runs for the most recent loop_end selection. This prevents
            # reverting to the original sequence after every server restart.
            if next_vh is None and len(run_ids) > 1:
                async with AsyncSessionLocal() as db:
                    for prior_run_id in reversed(run_ids[:-1]):
                        prior_row = await db.get(RunRow, prior_run_id)
                        if prior_row and prior_row.status == "succeeded":
                            prior_data = json.loads(prior_row.data or "{}")
                            prior_run = Run.model_validate(prior_data)
                            prior_vh, prior_vl = _extract_next_sequence(prior_run)
                            if prior_vh:
                                next_vh, next_vl = prior_vh, prior_vl
                                break

            next_pipeline = _patch_pipeline(pipeline, iteration + 1, next_vh, next_vl, loop_history)
            next_run = await create_run(next_pipeline, loop_id=loop_row.id, iteration=iteration + 1)

            async with AsyncSessionLocal() as db:
                lr = await db.get(LoopRunRow, loop_row.id)
                if lr:
                    all_ids = json.loads(lr.run_ids or "[]")
                    if next_run.id not in all_ids:
                        all_ids.append(next_run.id)
                    lr.run_ids = json.dumps(all_ids)
                    lr.current_iteration = iteration + 1
                    lr.status = "running"
                    lr.updated_at = datetime.utcnow()
                    await db.commit()

            logger.warning("Loop %s: resumed at iter %d after restart (run %s)", loop_row.id, iteration + 1, next_run.id)
            asyncio.ensure_future(execute_run(next_run.id))
        except Exception as exc:
            logger.warning("Loop %s: resume failed at restart: %s", loop_row.id, exc)


async def _load_published_custom_tools() -> None:
    """Re-register any previously-published Workshop tools into the adapter map."""
    from app.workers.tasks import _ADAPTER_MAP
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CustomToolRow).where(CustomToolRow.status == "published")
            )
        ).scalars().all()
    for row in rows:
        _ADAPTER_MAP[f"custom_{row.id}"] = (
            "app.tools.adapters.custom_tool",
            "CustomToolAdapter",
        )
    if rows:
        logger.info("Loaded %d published custom tool(s) into adapter map", len(rows))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await _migrate(conn)
    _kill_orphaned_haddock()
    await _mark_orphaned_runs()
    await _resume_interrupted_loops()
    tool_registry.load()
    await _load_published_custom_tools()
    yield
    await engine.dispose()


app = FastAPI(title="Protein Design Platform API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tools.router, prefix="/api/tools", tags=["tools"])
app.include_router(pipelines.router, prefix="/api/pipelines", tags=["pipelines"])
app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(ml_analysis.router, prefix="/api/ml-analysis", tags=["ml-analysis"])
app.include_router(results.router, prefix="/api/results", tags=["results"])
app.include_router(sequences.router, prefix="/api/sequences", tags=["sequences"])
app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])
app.include_router(trained_models.router, prefix="/api/models", tags=["models"])
app.include_router(loop_runs.router, prefix="/api/loop-runs", tags=["loop-runs"])
app.include_router(workshop.router, prefix="/api/workshop", tags=["workshop"])
app.include_router(md_ground.router, prefix="/api/md-ground", tags=["md-ground"])
app.include_router(md_ground_ws.router, tags=["md-ground-ws"])
app.include_router(ws.router, prefix="/ws", tags=["ws"])
app.include_router(compute.router, prefix="/ws/compute", tags=["compute"])
app.include_router(workshop.ws_router, tags=["workshop-ws"])

if _TOOLS_DIR.exists():
    app.mount("/papers", StaticFiles(directory=str(_TOOLS_DIR)), name="papers")


@app.get("/health")
async def health():
    return {"status": "ok"}
