import pytest
from httpx import ASGITransport, AsyncClient

import app.db as db
from app.config import get_settings
from app.main import app


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
