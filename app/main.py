from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app import __version__
from app.config import get_settings

# Annotated DI style (instead of a Depends() default): keeps ruff's B008 happy,
# reads cleanly under type checkers, and is what current FastAPI docs recommend.
SessionDep = Annotated[AsyncSession, Depends(db.get_session)]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    version: str


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Owns the engine lifecycle: created on startup, connections released on shutdown.
    db.init_engine(get_settings().database_url)
    yield
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
            database_ok = await db.check_database(session)
        except Exception:
            # Deliberately broad: any driver/connection failure must read as unhealthy,
            # never bubble up as a 500 from a probe endpoint.
            database_ok = False
        if not database_ok:
            # 503 (not 500) so load balancers / orchestrators stop routing to this instance.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="database unavailable",
            )
        return HealthResponse(status="ok", database=True, version=__version__)

    return app


app = create_app()
