from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

# Resolve relative sqlite paths to an absolute path anchored at backend/
# so the DB location is stable regardless of which directory uvicorn is started from.
_database_url = settings.database_url
if _database_url.startswith("sqlite") and ":///./" in _database_url:
    _backend_dir = Path(__file__).parents[2]  # backend/app/db/session.py → backend/
    _rel = _database_url.split(":///./", 1)[1]
    _database_url = f"sqlite+aiosqlite:///{_backend_dir / _rel}"

engine = create_async_engine(
    _database_url,
    echo=settings.app_env == "development",
    # SQLite needs this for concurrent access from multiple coroutines
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:  # type: ignore[return]
    async with AsyncSessionLocal() as session:
        yield session
