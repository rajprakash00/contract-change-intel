"""Integration tests for the extraction HTTP surface.

POST enqueues a job row and returns 202 immediately — no LLM call in the
request path. GET /extraction-jobs/{id} polls status, tenant-scoped.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

import app.db as db
from app.models.document import Document, DocumentStatus
from app.models.extraction_job import ExtractionJob
from tests.fake_jwks import bearer

TEXT_MIME = "text/plain"


@pytest.fixture(autouse=True)
async def clean_tables(client: AsyncClient) -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ExtractionJob))
        await session.execute(delete(Document))
        await session.commit()


async def upload_document(client: AsyncClient, tenant_id: uuid.UUID) -> dict:
    response = await client.post(
        "/documents",
        files={"file": ("msa.txt", b"agreement text", TEXT_MIME)},
        headers=bearer(tenant_id),
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


async def mark_parsed(document_id: str) -> None:
    """Flip a document to `parsed` directly: extraction requires a completed
    ingestion, and these tests exercise extraction, not the ingestion run."""
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.parsed
        await session.commit()


async def test_enqueue_returns_202_queued_job_without_running_it(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    document = await upload_document(client, tenant_id)
    await mark_parsed(document["id"])

    response = await client.post(f"/documents/{document['id']}/extraction", headers=headers)

    assert response.status_code == 202
    body = response.json()
    assert body["document_id"] == document["id"]
    assert body["tenant_id"] == str(tenant_id)
    assert body["status"] == "queued"
    assert body["result"] is None
    assert body["error"] is None


async def test_enqueue_before_ingestion_is_409_naming_no_ingestion_job(
    client: AsyncClient,
) -> None:
    # Fresh upload: never ingested, so there is no ingestion job to name.
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    document = await upload_document(client, tenant_id)

    response = await client.post(f"/documents/{document['id']}/extraction", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == {"ingestion_job_id": None}


async def test_enqueue_unknown_document_is_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/documents/{uuid.uuid4()}/extraction", headers=bearer(uuid.uuid4())
    )
    assert response.status_code == 404


async def test_enqueue_while_active_job_exists_is_409_with_existing_job_id(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    document = await upload_document(client, tenant_id)
    await mark_parsed(document["id"])
    first = await client.post(f"/documents/{document['id']}/extraction", headers=headers)
    assert first.status_code == 202

    conflict = await client.post(f"/documents/{document['id']}/extraction", headers=headers)

    assert conflict.status_code == 409
    assert conflict.json()["detail"] == {"existing_job_id": first.json()["id"]}


async def test_enqueue_other_tenant_document_is_404(client: AsyncClient) -> None:
    document = await upload_document(client, uuid.uuid4())
    response = await client.post(
        f"/documents/{document['id']}/extraction", headers=bearer(uuid.uuid4())
    )
    assert response.status_code == 404


async def test_get_job_returns_status_for_owning_tenant(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    document = await upload_document(client, tenant_id)
    await mark_parsed(document["id"])
    enqueued = await client.post(f"/documents/{document['id']}/extraction", headers=headers)
    job_id = enqueued.json()["id"]

    response = await client.get(f"/extraction-jobs/{job_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert response.json()["status"] == "queued"


async def test_get_job_is_tenant_scoped(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    document = await upload_document(client, tenant_id)
    await mark_parsed(document["id"])
    enqueued = await client.post(
        f"/documents/{document['id']}/extraction", headers=bearer(tenant_id)
    )
    job_id = enqueued.json()["id"]

    stranger = await client.get(f"/extraction-jobs/{job_id}", headers=bearer(uuid.uuid4()))
    missing = await client.get(f"/extraction-jobs/{uuid.uuid4()}", headers=bearer(tenant_id))

    assert stranger.status_code == 404
    assert missing.status_code == 404


async def test_missing_bearer_token_rejected(client: AsyncClient) -> None:
    document = await upload_document(client, uuid.uuid4())
    response = await client.post(f"/documents/{document['id']}/extraction")
    assert response.status_code == 401
