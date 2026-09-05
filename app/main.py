import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.api.routes.change_reports as change_reports
import app.db as db
from app.api.routes import documents, extraction, health, ingestion, reviews, search
from app.config import get_settings
from app.errors import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware import RequestIDMiddleware

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
    app.add_middleware(RequestIDMiddleware)
    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(extraction.router)
    app.include_router(ingestion.router)
    app.include_router(search.router)
    app.include_router(change_reports.router)
    app.include_router(reviews.router)
    register_exception_handlers(app)
    return app


app = create_app()
