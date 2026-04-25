"""End-to-end API tests using an in-memory SQLite DB."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.db.models import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
async def client():
    # Spin up a fresh in-memory DB for each test
    test_engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_tools_empty(client):
    r = await client.get("/api/tools/")
    assert r.status_code == 200
    tools = r.json()
    assert isinstance(tools, list)
    assert any(tool["id"] == "abmap" for tool in tools)


@pytest.mark.asyncio
async def test_pipeline_crud(client):
    payload = {
        "id": "pipe-1",
        "name": "Test pipeline",
        "schema_version": "1",
        "nodes": [],
        "edges": [],
    }
    r = await client.post("/api/pipelines/", json=payload)
    assert r.status_code == 201

    r = await client.get("/api/pipelines/pipe-1")
    assert r.status_code == 200
    assert r.json()["name"] == "Test pipeline"

    r = await client.get("/api/pipelines/")
    assert any(p["id"] == "pipe-1" for p in r.json())

    await client.delete("/api/pipelines/pipe-1")
    r = await client.get("/api/pipelines/pipe-1")
    assert r.status_code == 404
