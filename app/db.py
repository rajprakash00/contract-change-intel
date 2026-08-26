from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Module-level singletons: one engine per process
# init_engine/dispose_engine are owned by the app lifespan (tests call them directly because
# httpx's ASGITransport does not run lifespan events).
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_engine(url: str) -> None:
    global _engine, _sessionmaker
    # pool_pre_ping emits a cheap liveness check before reusing a pooled connection,
    # so a Postgres restart degrades into reconnects instead of stale-connection errors.
    _engine = create_async_engine(url, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Direct access to the session factory for scripts and test cleanup."""
    if _sessionmaker is None:
        raise RuntimeError("database engine not initialised; call init_engine first")
    return _sessionmaker


async def dispose_engine() -> None:
    if _engine is not None:
        await _engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request, closed on exit."""
    if _sessionmaker is None:
        raise RuntimeError("database engine not initialised; call init_engine first")
    async with _sessionmaker() as session:
        yield session


async def check_database(session: AsyncSession) -> None:
    """Return quietly if Postgres answers a trivial query; raise on any failure."""
    await session.execute(text("SELECT 1"))
