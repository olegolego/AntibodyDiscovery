from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import analysis, artifacts, compute, pipelines, results, runs, sequences, tools, ws
from app.config import settings
from app.db.models import Base
from app.db.session import engine
from app.tools.registry import tool_registry

_TOOLS_DIR = Path(__file__).parent.parent.parent / "tools"


async def _migrate(conn) -> None:
    """Add columns introduced after initial schema creation."""
    await conn.run_sync(Base.metadata.create_all)
    # Add new columns to docking_results if they don't exist yet
    for col in ("tool_id TEXT", "extra_data TEXT"):
        try:
            await conn.execute(
                __import__("sqlalchemy").text(
                    f"ALTER TABLE docking_results ADD COLUMN {col}"
                )
            )
        except Exception:
            pass  # column already exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await _migrate(conn)
    tool_registry.load()
    yield
    await engine.dispose()


app = FastAPI(title="Protein Design Platform API", version="0.1.0", lifespan=lifespan, redirect_slashes=False)

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
app.include_router(ws.router, prefix="/ws", tags=["ws"])
app.include_router(compute.router, prefix="/ws/compute", tags=["compute"])

if _TOOLS_DIR.exists():
    app.mount("/papers", StaticFiles(directory=str(_TOOLS_DIR)), name="papers")


@app.get("/health")
async def health():
    return {"status": "ok"}
