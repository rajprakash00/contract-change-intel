import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.db as db
from app.api import api_router
from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


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
    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
