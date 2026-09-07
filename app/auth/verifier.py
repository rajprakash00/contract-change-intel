"""Bearer JWT verification: an Auth0-signed token becomes a Principal —
the tenant, role, and subject the rest of the app scopes and audits on.

Verification is strict: RS256 only, against the issuer/audience from settings,
with required standard claims. Claim mapping (tenant UUID + role) happens here
so no route or service ever reads token claims directly.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum

import jwt

from app.auth.jwks import JwksClient
from app.config import Settings

# Auth0 custom claims must be namespaced to avoid colliding with reserved ones.
TENANT_CLAIM = "https://cci/tenant_id"
ROLE_CLAIM = "https://cci/role"

SUPPORTED_ALGORITHMS = ["RS256"]
# Small leeway for clock skew between this host and the issuer.
LEEWAY_SECONDS = 30


class Role(StrEnum):
    ADMIN = "admin"
    REVIEWER = "reviewer"


@dataclass(frozen=True)
class Principal:
    tenant_id: uuid.UUID
    role: Role
    subject: str


class AuthenticationError(Exception):
    """The bearer token is missing, malformed, or untrusted (HTTP 401)."""


class AuthorizationError(Exception):
    """The principal's role does not meet the endpoint's requirement (HTTP 403)."""


class AuthNotConfiguredError(Exception):
    """Auth settings are missing — a deployment problem, not a client error (HTTP 503)."""


async def verify_token(jwks: JwksClient, settings: Settings, token: str) -> Principal:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise AuthenticationError("malformed token") from None
    key = await jwks.get_key(str(header.get("kid") or ""))
    if key is None:
        raise AuthenticationError("unknown signing key")
    try:
        claims = jwt.decode(
            token,
            key.key,
            algorithms=SUPPORTED_ALGORITHMS,
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
            leeway=LEEWAY_SECONDS,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("token has expired") from None
    except jwt.PyJWTError:
        raise AuthenticationError("invalid token") from None

    subject = claims.get("sub")
    tenant_raw = claims.get(TENANT_CLAIM)
    role_raw = claims.get(ROLE_CLAIM)
    if not subject or not tenant_raw or not role_raw:
        raise AuthenticationError("token is missing tenant, role, or subject claims")
    try:
        tenant_id = uuid.UUID(str(tenant_raw))
    except ValueError:
        raise AuthenticationError("tenant claim is not a valid tenant id") from None
    try:
        role = Role(str(role_raw))
    except ValueError:
        raise AuthenticationError("unknown role claim") from None
    return Principal(tenant_id=tenant_id, role=role, subject=str(subject))
