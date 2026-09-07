import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient

import app.db as db
from app.api.deps import get_jwks_client
from app.config import get_settings
from app.main import app
from tests.fake_jwks import TEST_AUDIENCE, TEST_DOMAIN, fake_jwks_client


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """Apply migrations once per test session against the configured database.

    Keeps tests self-contained: CI or a fresh local db only needs to be running,
    not pre-migrated. URL comes from app settings, same as env.py.
    """
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
async def auth_env(monkeypatch):
    """Every API test runs with auth on: the app sees a fake Auth0 domain via
    settings, and the JWKS wire is faked at the transport seam
    (tests/fake_jwks.py) — verification itself stays real."""
    monkeypatch.setenv("AUTH0_DOMAIN", TEST_DOMAIN)
    monkeypatch.setenv("AUTH0_AUDIENCE", TEST_AUDIENCE)
    get_settings.cache_clear()
    try:
        async with fake_jwks_client() as jwks:
            app.dependency_overrides[get_jwks_client] = lambda: jwks
            yield
    finally:
        app.dependency_overrides.pop(get_jwks_client, None)
        get_settings.cache_clear()


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
