"""Integration tests for the Change Report HTTP surface.

POST /agreements/{id}/change-report names the amendment and returns 202
immediately — no LLM call in the request path. GET
/change-report-jobs/{id} polls status, tenant-scoped. Prerequisite gaps
(ingestion or extraction on either version) are 409s whose detail names
the first missing job.
"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

import app.db as db
from app.models.audit_log import AuditLog
from app.models.change_report_job import ChangeReportJob, ChangeReportJobStatus
from app.models.document import Document, DocumentStatus
from app.models.document_text import DocumentText
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from tests.fake_jwks import bearer

BASE_TEXT = "2.1 Delivery\n\nLICENSOR shall deliver within 14 days."
AMENDED_TEXT = "2.1 Delivery\n\nLICENSOR shall deliver within 30 days."
EXPLANATION_OUTPUT = json.dumps(
    {"changes": [{"index": 0, "description": "The delivery window doubles.", "severity": "high"}]}
)


@pytest.fixture(autouse=True)
async def clean_tables(client: AsyncClient) -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ChangeReportJob))
        await session.execute(delete(ExtractionJob))
        await session.execute(delete(DocumentText))
        await session.execute(delete(Document))
        await session.commit()


async def make_document(
    client: AsyncClient, tenant_id: uuid.UUID, *, amends: str | None = None
) -> dict:
    response = await client.post(
        "/documents",
        files={"file": ("agreement.txt", uuid.uuid4().hex.encode(), "text/plain")},
        headers=bearer(tenant_id),
        data={"amends_document_id": amends} if amends else None,
    )
    assert response.status_code == 201
    return response.json()  # type: ignore[no-any-return]


async def make_ready_pair(client: AsyncClient, tenant_id: uuid.UUID) -> tuple[dict, dict]:
    """Base + amendment both parsed with completed extraction jobs."""
    base = await make_document(client, tenant_id)
    amended = await make_document(client, tenant_id, amends=base["id"])
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        for document_id in (base["id"], amended["id"]):
            document = await session.get(Document, uuid.UUID(document_id))
            assert document is not None
            document.status = DocumentStatus.parsed
            session.add(
                ExtractionJob(
                    tenant_id=tenant_id,
                    document_id=document.id,
                    status=ExtractionJobStatus.completed,
                    result={},
                )
            )
            session.add(
                DocumentText(
                    document_id=document.id,
                    tenant_id=tenant_id,
                    text=BASE_TEXT if document_id == base["id"] else AMENDED_TEXT,
                    page_map=[],
                )
            )
        await session.commit()
    return base, amended


async def make_ready(client: AsyncClient, tenant_id: uuid.UUID, document_id: str) -> None:
    """Mark one document parsed with a completed extraction job + parsed text."""
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        document = await session.get(Document, uuid.UUID(document_id))
        assert document is not None
        document.status = DocumentStatus.parsed
        session.add(
            ExtractionJob(
                tenant_id=tenant_id,
                document_id=document.id,
                status=ExtractionJobStatus.completed,
                result={},
            )
        )
        session.add(
            DocumentText(
                document_id=document.id,
                tenant_id=tenant_id,
                text=BASE_TEXT,
                page_map=[],
            )
        )
        await session.commit()


def body(amendment_id: str) -> dict:
    return {"amendment_document_id": amendment_id}


async def test_post_returns_202_queued_job_for_the_named_pair(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base, amended = await make_ready_pair(client, tenant_id)

    response = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )

    assert response.status_code == 202
    job = response.json()
    assert job["base_document_id"] == base["id"]
    assert job["amended_document_id"] == amended["id"]
    assert job["status"] == "queued"
    assert job["result"] is None


async def test_post_before_prerequisites_is_409_naming_the_first_missing_job(
    client: AsyncClient,
) -> None:
    # Nothing is ingested or extracted: the first gap in
    # base-ingestion → base-extraction → amendment-ingestion →
    # amendment-extraction order is the base ingestion, never run.
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base = await make_document(client, tenant_id)
    amended = await make_document(client, tenant_id, amends=base["id"])

    response = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "document_id": base["id"],
        "kind": "ingestion",
        "job_id": None,
    }


async def test_post_with_unlinked_amendment_is_409(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base = await make_document(client, tenant_id)
    unrelated = await make_document(client, tenant_id)

    response = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(unrelated["id"]), headers=headers
    )

    assert response.status_code == 409


async def test_post_unknown_base_is_404(client: AsyncClient) -> None:
    response = await client.post(
        f"/agreements/{uuid.uuid4()}/change-report",
        json=body(str(uuid.uuid4())),
        headers=bearer(uuid.uuid4()),
    )
    assert response.status_code == 404


async def test_post_unknown_amendment_is_404(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base = await make_document(client, tenant_id)

    response = await client.post(
        f"/agreements/{base['id']}/change-report",
        json=body(str(uuid.uuid4())),
        headers=headers,
    )

    assert response.status_code == 404


async def test_post_foreign_amendment_is_404(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base = await make_document(client, tenant_id)
    foreign = await make_document(client, uuid.uuid4())

    response = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(foreign["id"]), headers=headers
    )

    assert response.status_code == 404


async def test_get_change_report_job_polls_status(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base, amended = await make_ready_pair(client, tenant_id)
    enqueued = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )
    job_id = enqueued.json()["id"]

    response = await client.get(f"/change-report-jobs/{job_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["id"] == job_id
    assert response.json()["status"] == "queued"


async def test_get_change_report_job_is_tenant_scoped(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    base, amended = await make_ready_pair(client, tenant_id)
    enqueued = await client.post(
        f"/agreements/{base['id']}/change-report",
        json=body(amended["id"]),
        headers=bearer(tenant_id),
    )
    job_id = enqueued.json()["id"]

    stranger = await client.get(f"/change-report-jobs/{job_id}", headers=bearer(uuid.uuid4()))
    missing = await client.get(
        f"/change-report-jobs/{uuid.uuid4()}",
        headers=bearer(tenant_id),
    )

    assert stranger.status_code == 404
    assert missing.status_code == 404


async def test_list_change_report_jobs_returns_every_job_newest_first_with_status(
    client: AsyncClient,
) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base, amended = await make_ready_pair(client, tenant_id)
    second = await make_document(client, tenant_id, amends=base["id"])
    await make_ready(client, tenant_id, second["id"])
    first = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )
    second_job = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(second["id"]), headers=headers
    )
    assert first.status_code == 202 and second_job.status_code == 202
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        older = await session.get(ChangeReportJob, uuid.UUID(first.json()["id"]))
        assert older is not None
        older.created_at = datetime.now(UTC) - timedelta(seconds=10)
        completed = await session.get(ChangeReportJob, uuid.UUID(second_job.json()["id"]))
        assert completed is not None
        completed.status = ChangeReportJobStatus.completed
        await session.commit()

    response = await client.get(f"/agreements/{base['id']}/change-report-jobs", headers=headers)

    assert response.status_code == 200
    jobs = response.json()
    assert [j["id"] for j in jobs] == [second_job.json()["id"], first.json()["id"]]
    assert [j["status"] for j in jobs] == ["completed", "queued"]


async def test_list_change_report_jobs_is_tenant_scoped(client: AsyncClient) -> None:
    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base, amended = await make_ready_pair(client, tenant_id)
    enqueued = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )
    assert enqueued.status_code == 202

    stranger = await client.get(
        f"/agreements/{base['id']}/change-report-jobs", headers=bearer(uuid.uuid4())
    )
    unknown = await client.get(f"/agreements/{uuid.uuid4()}/change-report-jobs", headers=headers)

    assert stranger.status_code == 404
    assert unknown.status_code == 404


async def test_list_change_report_jobs_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.get(f"/agreements/{uuid.uuid4()}/change-report-jobs")
    assert response.status_code == 401


async def test_post_requires_bearer_token(client: AsyncClient) -> None:
    response = await client.post(
        f"/agreements/{uuid.uuid4()}/change-report", json=body(str(uuid.uuid4()))
    )
    assert response.status_code == 401


async def test_enqueue_writes_an_audit_row_for_the_change_report(client: AsyncClient) -> None:
    from sqlalchemy import select

    tenant_id = uuid.uuid4()
    headers = bearer(tenant_id)
    base, amended = await make_ready_pair(client, tenant_id)

    response = await client.post(
        f"/agreements/{base['id']}/change-report", json=body(amended["id"]), headers=headers
    )

    assert response.status_code == 202
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        rows = (
            (await session.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
    assert [row.action for row in rows] == [
        "document.upload",
        "document.upload",
        "change_report.enqueue",
    ]
    row = rows[-1]
    assert row.action == "change_report.enqueue"
    assert row.resource_type == "change_report_job"
    assert row.resource_id == uuid.UUID(response.json()["id"])
    assert row.request_id == response.headers["x-request-id"]
    assert row.detail == {
        "base_document_id": base["id"],
        "amended_document_id": amended["id"],
    }
