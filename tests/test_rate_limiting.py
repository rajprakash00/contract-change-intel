"""Integration tests for the per-tenant LLM rate limit (ADR-010).

The two LLM-enqueue POSTs spend a per-tenant budget (settings knobs) before
the service runs: 429 with Retry-After once it is spent, other tenants and
other endpoint kinds unaffected, and the window reset admits new requests.
"""

import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select

import app.db as db
import app.ratelimit as ratelimit
from app.config import get_settings
from app.models.change_report_job import ChangeReportJob
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_text import DocumentText
from app.models.extraction_job import ExtractionJob
from app.models.ingestion_job import IngestionJob
from app.models.review_item import ReviewItem
from tests.fake_jwks import bearer, mint_token
from tests.test_change_report_api import body, make_document, make_ready, make_ready_pair
from tests.test_extraction_api import mark_parsed

LIMIT_PER_HOUR = 2


def bearer_long_lived(tenant_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint_token(tenant_id, expires_in=7200)}"}


@pytest.fixture(autouse=True)
async def clean_tables(client: AsyncClient) -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ReviewItem))
        await session.execute(delete(ChangeReportJob))
        await session.execute(delete(ExtractionJob))
        await session.execute(delete(IngestionJob))
        await session.execute(delete(DocumentChunk))
        await session.execute(delete(DocumentText))
        await session.execute(delete(Document))
        await session.commit()


@pytest.fixture(autouse=True)
def isolated_budget(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test gets a fresh budget and a small, explicit limit: counter
    state is process-global, and the settings cache must pick up the env
    overrides before the first request of the test."""
    ratelimit.reset()
    monkeypatch.setenv("RATE_LIMIT_EXTRACTION_PER_HOUR", str(LIMIT_PER_HOUR))
    monkeypatch.setenv("RATE_LIMIT_CHANGE_REPORT_PER_HOUR", str(LIMIT_PER_HOUR))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def time_travel(monkeypatch: pytest.MonkeyPatch) -> Callable[[], AbstractContextManager[None]]:
    """Context shifting the limiter's clock past the hour window without
    waiting for it. Entering it shifts the process-wide clock, so tokens must
    be minted (and long-lived) before entering."""

    @contextmanager
    def shift() -> Iterator[None]:
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + 3601)
        yield

    yield shift


async def _parsed_document(
    client: AsyncClient, tenant_id: uuid.UUID, headers: dict[str, str] | None = None
) -> dict:
    # Extraction allows one queued job per document and uploads are
    # content-addressed, so each budget attempt needs its own document with
    # its own bytes.
    response = await client.post(
        "/documents",
        files={"file": ("msa.txt", uuid.uuid4().hex.encode(), "text/plain")},
        headers=headers or bearer(tenant_id),
    )
    assert response.status_code == 201
    document = response.json()
    await mark_parsed(document["id"])
    return document


async def test_extraction_enqueue_is_429_once_the_tenant_budget_is_spent(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    documents = [
        await _parsed_document(client, tenant_id, headers) for _ in range(LIMIT_PER_HOUR + 1)
    ]
    for document in documents[:LIMIT_PER_HOUR]:
        response = await client.post(f"/documents/{document['id']}/extraction", headers=headers)
        assert response.status_code == 202

    exceeded = await client.post(
        f"/documents/{documents[LIMIT_PER_HOUR]['id']}/extraction", headers=headers
    )

    assert exceeded.status_code == 429
    retry_after = int(exceeded.headers["Retry-After"])
    assert 1 <= retry_after <= 3600
    assert "rate limit exceeded" in exceeded.json()["detail"]
    # The budget is spent before the service runs: no third job row exists.
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        jobs = (
            await session.scalars(
                select(func.count())
                .select_from(ExtractionJob)
                .where(ExtractionJob.tenant_id == tenant_id)
            )
        ).one()
    assert jobs == LIMIT_PER_HOUR


async def test_change_report_enqueue_is_429_once_the_tenant_budget_is_spent(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base, amended = await make_ready_pair(client, tenant_id)
    second_amendment = await make_document(client, tenant_id, amends=base["id"])
    await make_ready(client, tenant_id, second_amendment["id"])

    first = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )
    second = await client.post(
        f"/agreements/{base['id']}/change-report",
        json=body(second_amendment["id"]),
        headers=headers,
    )
    exceeded = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )

    assert first.status_code == 202
    assert second.status_code == 202
    # The third attempt would be a 409 (amendment already reported), but the
    # limit fires first: attempts spend the budget, not successful passes.
    assert exceeded.status_code == 429
    assert "Retry-After" in exceeded.headers


async def test_budgets_are_per_tenant(client: AsyncClient) -> None:
    exhausted_tenant = uuid.uuid4()
    other_tenant = uuid.uuid4()
    exhausted_headers = bearer(exhausted_tenant)
    for _ in range(LIMIT_PER_HOUR):
        document = await _parsed_document(client, exhausted_tenant)
        await client.post(f"/documents/{document['id']}/extraction", headers=exhausted_headers)
    other_document = await _parsed_document(client, other_tenant)
    await client.post(f"/documents/{other_document['id']}/extraction", headers=bearer(other_tenant))

    response = await client.post(
        f"/documents/{other_document['id']}/extraction", headers=exhausted_headers
    )

    assert response.status_code == 429
    # The exhausted tenant does not touch the other tenant's budget: a fresh
    # document still enqueues.
    fresh = await _parsed_document(client, other_tenant)
    unaffected = await client.post(
        f"/documents/{fresh['id']}/extraction", headers=bearer(other_tenant)
    )

    assert unaffected.status_code == 202


async def test_endpoint_kinds_have_separate_budgets(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    for _ in range(LIMIT_PER_HOUR):
        document = await _parsed_document(client, tenant_id)
        await client.post(f"/documents/{document['id']}/extraction", headers=headers)
    base, amended = await make_ready_pair(client, tenant_id)

    response = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )

    assert response.status_code == 202


async def test_window_expiry_admits_new_requests(
    client: AsyncClient, time_travel: Callable[[], AbstractContextManager[None]]
) -> None:
    tenant_id = uuid.uuid4()
    # Long-lived token: the test shifts the clock past the window, which
    # would otherwise expire the default 300s bearer mid-test.
    headers = bearer_long_lived(tenant_id)
    documents = [
        await _parsed_document(client, tenant_id, headers) for _ in range(LIMIT_PER_HOUR + 1)
    ]
    for document in documents[:LIMIT_PER_HOUR]:
        await client.post(f"/documents/{document['id']}/extraction", headers=headers)
    exceeded = await client.post(
        f"/documents/{documents[LIMIT_PER_HOUR]['id']}/extraction", headers=headers
    )
    assert exceeded.status_code == 429

    with time_travel():
        response = await client.post(
            f"/documents/{documents[LIMIT_PER_HOUR]['id']}/extraction", headers=headers
        )

    assert response.status_code == 202


async def test_retry_after_naming_the_window_reset(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    documents = [await _parsed_document(client, tenant_id) for _ in range(LIMIT_PER_HOUR)]
    for document in documents:
        await client.post(f"/documents/{document['id']}/extraction", headers=headers)
    extra = await _parsed_document(client, tenant_id)

    exceeded = await client.post(f"/documents/{extra['id']}/extraction", headers=headers)

    assert int(exceeded.headers["Retry-After"]) <= 3600
