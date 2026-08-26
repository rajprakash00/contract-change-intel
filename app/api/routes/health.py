"""Liveness/readiness probe."""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

import app.db as db
from app import __version__
from app.api.deps import SessionDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    version: str


@router.get(
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
