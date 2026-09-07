"""Shared fake Auth0 wire for auth tests, mirroring tests/fake_openai.py:
the real JwksClient runs against an httpx.MockTransport serving a test JWKS,
so verification is exercised end to end without network.

One RSA keypair per test session — key generation is the only slow part.
"""

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.jwks import JwksClient
from app.auth.verifier import ROLE_CLAIM, TENANT_CLAIM

TEST_DOMAIN = "cci-test.auth0.com"
TEST_AUDIENCE = "https://cci-api.test"
TEST_KID = "test-signing-key"
TEST_SUB = "auth0|test-user"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
)


def _public_jwk() -> dict[str, Any]:
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key()))
    jwk["kid"] = TEST_KID
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return jwk


def jwks_body() -> bytes:
    return json.dumps({"keys": [_public_jwk()]}).encode()


def mint_token(
    tenant_id: Any,
    role: str = "admin",
    sub: str = TEST_SUB,
    *,
    expires_in: float = 300.0,
    kid: str = TEST_KID,
    **extra_claims: Any,
) -> str:
    """A token signed by the test key, carrying the claims the verifier maps.

    `extra_claims` overrides top-level claims; a claim set to None is dropped,
    for missing-claim tests (e.g. exp=None, TENANT_CLAIM=None).
    """
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": f"https://{TEST_DOMAIN}/",
        "aud": TEST_AUDIENCE,
        "sub": sub,
        "iat": now,
        "exp": now + int(expires_in),
        TENANT_CLAIM: str(tenant_id),
        ROLE_CLAIM: role,
    }
    claims.update(extra_claims)
    claims = {name: value for name, value in claims.items() if value is not None}
    headers = {"kid": kid} if kid else None
    return jwt.encode(claims, _PRIVATE_PEM, algorithm="RS256", headers=headers)


def bearer(tenant_id: Any, role: str = "admin", sub: str = TEST_SUB) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(tenant_id, role=role, sub=sub)}"}


@asynccontextmanager
async def fake_jwks_client() -> AsyncIterator[JwksClient]:
    """A JwksClient whose wire serves the test JWKS; the wire closes on exit."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=jwks_body())

    wire = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield JwksClient(TEST_DOMAIN, http_client=wire)
    finally:
        # JwksClient.aclose() skips caller-owned wires; close ours here.
        await wire.aclose()
