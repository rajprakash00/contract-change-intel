"""Shared FastAPI dependencies for route modules."""

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.auth.jwks import JwksClient
from app.auth.verifier import (
    AuthenticationError,
    AuthNotConfiguredError,
    AuthorizationError,
    Principal,
    Role,
    verify_token,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.llm.client import OpenAiClient
from app.request_context import actor_ctx

SessionDep = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


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


_jwks_clients: dict[tuple[str, float], JwksClient] = {}


def _jwks_client_for(domain: str, cache_seconds: float) -> JwksClient:
    # One client per (domain, cache) for the process lifetime, so the JWKS
    # cache is shared across requests instead of refetched per request.
    key = (domain, cache_seconds)
    if key not in _jwks_clients:
        _jwks_clients[key] = JwksClient(domain, cache_seconds=cache_seconds)
    return _jwks_clients[key]


async def aclose_cached_jwks_clients() -> None:
    """Release the wires of all cached clients; called from the lifespan."""
    for client in _jwks_clients.values():
        await client.aclose()
    _jwks_clients.clear()


def get_jwks_client(settings: SettingsDep) -> JwksClient:
    if not settings.auth0_domain or not settings.auth0_audience:
        raise AuthNotConfiguredError("auth is not configured: set AUTH0_DOMAIN and AUTH0_AUDIENCE")
    return _jwks_client_for(settings.auth0_domain, settings.auth_jwks_cache_seconds)


JwksClientDep = Annotated[JwksClient, Depends(get_jwks_client)]


async def get_principal(request: Request, jwks: JwksClientDep, settings: SettingsDep) -> Principal:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("missing bearer token")
    principal = await verify_token(jwks, settings, token.strip())
    # Correlates audit rows with the acting principal, like request_id above.
    actor_ctx.set(principal.subject)
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(*allowed: Role) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Dependency factory gating an endpoint on the principal's role."""

    async def authorize(principal: PrincipalDep) -> Principal:
        if principal.role not in allowed:
            raise AuthorizationError(f"role '{principal.role.value}' may not do this")
        return principal

    return authorize


# Writes are admin-only; the review queue is reviewer-or-admin; reads are for
# any authenticated principal of the tenant named in the token.
AdminPrincipal = Annotated[Principal, Depends(require_role(Role.ADMIN))]
ReviewerPrincipal = Annotated[Principal, Depends(require_role(Role.REVIEWER, Role.ADMIN))]


def llm_rate_limit(kind: ratelimit.Kind) -> Callable[..., Coroutine[Any, Any, None]]:
    """Dependency factory spending the tenant's budget for one endpoint kind
    (ADR-010); 429 with Retry-After once the budget is spent. Depending on
    AdminPrincipal directly keeps the role check ahead of the spend."""

    async def enforce(settings: SettingsDep, principal: AdminPrincipal) -> None:
        ratelimit.enforce(kind, str(principal.tenant_id), settings)

    return enforce


# Two real uses: the LLM-enqueue POSTs. Non-enqueue endpoints stay unlimited.
ExtractionRateLimit = Annotated[None, Depends(llm_rate_limit("extraction"))]
ChangeReportRateLimit = Annotated[None, Depends(llm_rate_limit("change_report"))]
