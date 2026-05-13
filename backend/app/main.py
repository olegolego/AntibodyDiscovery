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

from app.api import analysis, artifacts, compute, datasets, loop_runs, pipelines, results, runs, sequences, tools, workshop, ws
from app.config import settings
from app.db.models import Base, CustomToolRow, RunRow
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
    await _mark_orphaned_runs()
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
app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(results.router, prefix="/api/results", tags=["results"])
app.include_router(sequences.router, prefix="/api/sequences", tags=["sequences"])
app.include_router(datasets.router, prefix="/api/datasets", tags=["datasets"])
app.include_router(loop_runs.router, prefix="/api/loop-runs", tags=["loop-runs"])
app.include_router(workshop.router, prefix="/api/workshop", tags=["workshop"])
app.include_router(ws.router, prefix="/ws", tags=["ws"])
app.include_router(compute.router, prefix="/ws/compute", tags=["compute"])
app.include_router(workshop.ws_router, tags=["workshop-ws"])

if _TOOLS_DIR.exists():
    app.mount("/papers", StaticFiles(directory=str(_TOOLS_DIR)), name="papers")


@app.get("/health")
async def health():
    return {"status": "ok"}
