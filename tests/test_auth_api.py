"""W5·C auth integration: the API trusts only Auth0-signed bearer tokens,
maps their claims to Tenant + Role, and refuses everything else.

The JWKS wire is faked at the transport seam (tests/fake_jwks.py) — signing,
fetching, and claim verification are real.
"""

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import delete

import app.api.deps as deps
import app.db as db
import app.repositories.review_items as review_items_repo
from app.auth.jwks import JwksClient
from app.config import get_settings
from app.main import app
from app.models.review_item import ReviewItem, ReviewItemSource, ReviewItemStatus
from tests.fake_jwks import bearer, mint_token


@pytest.fixture(autouse=True)
async def clean_review_items(client: AsyncClient) -> AsyncIterator[None]:
    """The reviewer test seeds a review item pointing at its document; other
    test modules' cleanups delete documents, so the item must not outlive
    this module."""
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ReviewItem))
        await session.commit()


async def test_healthz_needs_no_token(client: AsyncClient) -> None:
    """The probe endpoint stays open; everything else is gated."""
    assert (await client.get("/healthz")).status_code == 200


async def test_missing_token_is_unauthorized_with_bearer_challenge(
    client: AsyncClient,
) -> None:
    response = await client.get("/documents")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["detail"]


async def test_non_bearer_scheme_is_unauthorized(client: AsyncClient) -> None:
    response = await client.get("/documents", headers={"Authorization": "Basic abc"})
    assert response.status_code == 401


async def test_garbage_token_is_unauthorized(client: AsyncClient) -> None:
    response = await client.get("/documents", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_expired_token_is_unauthorized(client: AsyncClient) -> None:
    expired = mint_token(uuid.uuid4(), expires_in=-(60 * 60))
    response = await client.get("/documents", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


async def test_token_for_wrong_audience_is_unauthorized(client: AsyncClient) -> None:
    wrong = mint_token(uuid.uuid4(), aud="https://other-api.test")
    response = await client.get("/documents", headers={"Authorization": f"Bearer {wrong}"})
    assert response.status_code == 401


async def test_token_for_wrong_issuer_is_unauthorized(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The issuer must match the configured Auth0 domain: a token minted for
    another tenant-directory fails even if that issuer signed with the same
    keys. Simulated by pointing the app's expected domain elsewhere while the
    wire still serves the same JWKS."""
    monkeypatch.setenv("AUTH0_DOMAIN", "other-tenant.auth0.com")
    get_settings.cache_clear()
    try:
        token = mint_token(uuid.uuid4())
        response = await client.get("/documents", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()


async def test_token_signed_by_unknown_key_is_unauthorized(client: AsyncClient) -> None:
    """A kid the JWKS never advertised fails even though the signature is
    well-formed — and forces one refetch before giving up."""
    stranger = mint_token(uuid.uuid4(), kid="rotated-away-kid")
    response = await client.get("/documents", headers={"Authorization": f"Bearer {stranger}"})
    assert response.status_code == 401
    assert "signing key" in response.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"sub": None},
        {"exp": None},
        {"iat": None},
        {"https://cci/tenant_id": None},
        {"https://cci/role": None},
        {"https://cci/tenant_id": "not-a-uuid"},
        {"https://cci/role": "superuser"},
    ],
)
async def test_token_missing_or_bogus_claims_is_unauthorized(
    client: AsyncClient, overrides: dict[str, object]
) -> None:
    token = mint_token(uuid.uuid4(), **overrides)
    response = await client.get("/documents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_valid_token_grants_access_and_scopes_the_tenant(
    client: AsyncClient,
) -> None:
    """The tenant is taken from the claim, not from any header: the token's
    tenant sees its own uploads, and another tenant's token sees none."""
    mine = uuid.uuid4()
    created = await client.post(
        "/documents",
        files={"file": ("a.txt", b"scoped by claim", "text/plain")},
        headers=bearer(mine),
    )
    assert created.status_code == 201

    mine_page = await client.get("/documents", headers=bearer(mine))
    assert [item["id"] for item in mine_page.json()["items"]] == [created.json()["id"]]

    theirs = await client.get("/documents", headers=bearer(uuid.uuid4()))
    assert theirs.status_code == 200
    assert theirs.json()["items"] == []


async def test_reviewer_role_cannot_upload_but_can_read(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    upload = await client.post(
        "/documents",
        files={"file": ("r.txt", b"reviewer upload", "text/plain")},
        headers=bearer(tenant_id, role="reviewer"),
    )
    assert upload.status_code == 403

    listing = await client.get("/documents", headers=bearer(tenant_id, role="reviewer"))
    assert listing.status_code == 200


async def test_admin_role_can_upload(client: AsyncClient) -> None:
    upload = await client.post(
        "/documents",
        files={"file": ("a.txt", b"admin upload", "text/plain")},
        headers=bearer(uuid.uuid4(), role="admin"),
    )
    assert upload.status_code == 201


async def test_reviewer_can_resolve_review_item(client: AsyncClient) -> None:
    """The review queue is reviewer-or-admin; document writes stay admin-only."""
    tenant_id = uuid.uuid4()
    created = await client.post(
        "/documents",
        files={"file": ("a.txt", b"reviewer gate", "text/plain")},
        headers=bearer(tenant_id, role="admin"),
    )
    assert created.status_code == 201
    item_id = await _pending_review_item(tenant_id, uuid.UUID(created.json()["id"]))

    resolved = await client.post(
        f"/review-items/{item_id}/disposition",
        json={"disposition": "approved"},
        headers=bearer(tenant_id, role="reviewer"),
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "approved"


async def test_reviewer_cannot_enqueue_jobs(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    created = await client.post(
        "/documents",
        files={"file": ("a.txt", b"reviewer gate", "text/plain")},
        headers=bearer(tenant_id, role="admin"),
    )
    assert created.status_code == 201
    document_id = created.json()["id"]

    forbidden = await client.post(
        f"/documents/{document_id}/ingestion",
        headers=bearer(tenant_id, role="reviewer"),
    )
    assert forbidden.status_code == 403


async def test_audit_rows_record_the_token_subject_as_actor(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    created = await client.post(
        "/documents",
        files={"file": ("a.txt", b"audited actor", "text/plain")},
        headers=bearer(tenant_id, sub="auth0|alice"),
    )
    assert created.status_code == 201

    trail = await client.get("/audit-log", headers=bearer(tenant_id))
    assert trail.json()["items"][0]["actor"] == "auth0|alice"


async def test_unconfigured_auth_is_service_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No Auth0 domain is a deployment problem: 503, never a silently open API."""
    monkeypatch.setenv("AUTH0_DOMAIN", "")
    get_settings.cache_clear()
    # The conftest seam override bypasses get_jwks_client; drop it so the
    # dependency's own settings check runs.
    app.dependency_overrides.pop(deps.get_jwks_client, None)
    try:
        response = await client.get("/documents", headers=bearer(uuid.uuid4()))
        assert response.status_code == 503
    finally:
        get_settings.cache_clear()


async def test_unreachable_jwks_is_bad_gateway(client: AsyncClient) -> None:
    """The identity provider being down is upstream failure, not a bad token."""
    wire = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    app.dependency_overrides[deps.get_jwks_client] = lambda: JwksClient(
        "cci-test.auth0.com", http_client=wire
    )
    try:
        response = await client.get("/documents", headers=bearer(uuid.uuid4()))
        assert response.status_code == 502
    finally:
        app.dependency_overrides.pop(deps.get_jwks_client, None)
        await wire.aclose()


async def _pending_review_item(tenant_id: uuid.UUID, document_id: uuid.UUID) -> uuid.UUID:
    """Seed one pending review item straight through the repo (no HTTP), the
    same persistence the extraction worker's routing uses."""
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        rows = await review_items_repo.create_many(
            session,
            tenant_id=tenant_id,
            source=ReviewItemSource("extraction"),
            document_id=document_id,
            job_id=uuid.uuid4(),
            items=[("obligation", {"clause_ref": "1.1", "owner": "Anyone"}, 0.5)],
        )
        assert rows[0].status is ReviewItemStatus.pending
        return rows[0].id
