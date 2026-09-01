"""Shared FastAPI dependencies for route modules."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.llm.client import OpenAiClient

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TenantId = Annotated[uuid.UUID, Header(alias="X-Tenant-Id")]


async def get_llm_client(settings: SettingsDep) -> AsyncIterator[OpenAiClient]:
    """One OpenAI client per request, closed with the request.

    Search embeds queries in the request path — the first synchronous LLM
    surface (ADR-006); job-based flows keep their LLM calls worker-side.
    """
    client = OpenAiClient(settings)
    try:
        yield client
    finally:
        await client.aclose()


LlmClientDep = Annotated[OpenAiClient, Depends(get_llm_client)]
