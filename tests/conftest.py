import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

import app.db as db
from app.config import get_settings
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Apply migrations once per test session against the configured database.

    Keeps tests self-contained: CI or a fresh local db only needs to be running,
    not pre-migrated. URL comes from app settings, same as env.py.
    """
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest.fixture
async def client():
    # httpx ASGITransport does not execute FastAPI lifespan events, so the engine is
    # initialised and disposed here exactly as the lifespan would in production.
    db.init_engine(get_settings().database_url)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http
    finally:
        await db.dispose_engine()
