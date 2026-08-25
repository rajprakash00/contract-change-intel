import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app import __version__
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(db.get_session)]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    version: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Owns the engine lifecycle: created on startup, connections released on shutdown.
    configure_logging(get_settings().log_level)
    logger.info("api starting")
    db.init_engine(get_settings().database_url)
    yield
    logger.info("api shutting down; disposing database engine")
    await db.dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(title="contract-change-intel", lifespan=lifespan)

    @app.get(
        "/healthz",
        response_model=HealthResponse,
        responses={503: {"description": "database unreachable"}},
    )
    async def healthz(session: SessionDep) -> HealthResponse:
        try:
            await db.check_database(session)
        except Exception:
            # Deliberately broad: any driver/connection failure must read as unhealthy,
            # never bubble up as a 500 from a probe endpoint. Logged so the real cause
            # is visible instead of a bare 503.
            logger.warning("healthz database check failed", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            ) from None
        return HealthResponse(status="ok", database=True, version=__version__)

    return app


app = create_app()
