"""Integration tests for the Review Queue HTTP surface (W5·A).

Workers create Review Items when Confidence falls below the threshold; the
reviewer acts here: list, get, and resolve. The state machine is flat —
pending → approved | edited | rejected — so a resolved item is terminal
(409 on any further resolution) and `edited` captures corrected values.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, select

import app.db as db
from app.models.audit_log import AuditLog
from app.models.document import Document
from app.models.review_item import ReviewItem, ReviewItemSource, ReviewItemStatus
from tests.fake_jwks import bearer


@pytest.fixture(autouse=True)
async def clean_tables(client: AsyncClient) -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ReviewItem))
        await session.execute(delete(AuditLog))
        await session.execute(delete(Document))
        await session.commit()


async def make_document(tenant_id: uuid.UUID) -> uuid.UUID:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        document = Document(
            tenant_id=tenant_id,
            filename="agreement.txt",
            mime_type="text/plain",
            sha256=uuid.uuid4().hex * 2,
        )
        session.add(document)
        await session.commit()
        return document.id


async def make_item(
    tenant_id: uuid.UUID,
    *,
    status: ReviewItemStatus = ReviewItemStatus.pending,
    source: ReviewItemSource = ReviewItemSource.extraction,
    item_type: str = "obligation",
    confidence: float = 0.4,
) -> ReviewItem:
    return ReviewItem(
        tenant_id=tenant_id,
        source=source,
        item_type=item_type,
        document_id=await make_document(tenant_id),
        job_id=uuid.uuid4(),
        payload={"clause_ref": "8.2", "description": "d", "confidence": confidence},
        confidence=confidence,
        status=status,
    )


async def seed(items: list[ReviewItem]) -> None:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        for item in items:
            session.add(item)
        await session.commit()


async def get(client: AsyncClient, path: str, tenant_id: uuid.UUID) -> Response:
    return await client.get(path, headers=bearer(tenant_id))


async def post(client: AsyncClient, path: str, tenant_id: uuid.UUID, body: dict) -> Response:
    return await client.post(path, json=body, headers=bearer(tenant_id))


class TestListReviewItems:
    async def test_lists_pending_items_for_the_tenant(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])
        # A separate transaction so created_at (transaction start time)
        # differs and the oldest-first order is deterministic.
        approved = await make_item(tenant_id, status=ReviewItemStatus.approved)
        await seed([approved])

        response = await get(client, "/review-items", tenant_id)

        assert response.status_code == 200
        rows = response.json()["items"]
        assert [row["id"] for row in rows] == [str(item.id), str(approved.id)]
        assert rows[0]["source"] == "extraction"
        assert rows[0]["item_type"] == "obligation"
        assert rows[0]["status"] == "pending"
        assert rows[0]["payload"]["clause_ref"] == "8.2"
        assert rows[0]["corrected_values"] is None
        assert rows[0]["resolved_at"] is None

    async def test_status_filter_narrows_the_list(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        rejected = await make_item(tenant_id, status=ReviewItemStatus.rejected)
        await seed([rejected, await make_item(tenant_id)])

        response = await get(client, "/review-items?status=rejected", tenant_id)

        assert [row["id"] for row in response.json()["items"]] == [str(rejected.id)]

    async def test_list_is_tenant_scoped(self, client: AsyncClient) -> None:
        await seed([await make_item(uuid.uuid4())])

        response = await get(client, "/review-items", uuid.uuid4())

        assert response.json()["items"] == []


class TestGetReviewItem:
    async def test_returns_one_item(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        response = await get(client, f"/review-items/{item.id}", tenant_id)

        assert response.status_code == 200
        assert response.json()["id"] == str(item.id)

    async def test_unknown_or_foreign_item_is_404(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        foreign = await get(client, f"/review-items/{item.id}", uuid.uuid4())
        missing = await get(client, f"/review-items/{uuid.uuid4()}", tenant_id)

        assert foreign.status_code == 404
        assert missing.status_code == 404


class TestResolveReviewItem:
    async def test_approval_resolves_a_pending_item(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        response = await post(
            client, f"/review-items/{item.id}/disposition", tenant_id, {"disposition": "approved"}
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"
        assert body["corrected_values"] is None
        assert body["resolved_at"] is not None

    async def test_edited_resolution_captures_corrected_values(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])
        corrected = {"clause_ref": "8.2", "description": "corrected", "confidence": 0.4}

        response = await post(
            client,
            f"/review-items/{item.id}/disposition",
            tenant_id,
            {"disposition": "edited", "corrected_values": corrected},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "edited"
        assert response.json()["corrected_values"] == corrected

    async def test_rejection_resolves_a_pending_item(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        response = await post(
            client, f"/review-items/{item.id}/disposition", tenant_id, {"disposition": "rejected"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    async def test_resolution_is_terminal_no_re_entry(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])
        first = await post(
            client, f"/review-items/{item.id}/disposition", tenant_id, {"disposition": "approved"}
        )
        assert first.status_code == 200

        second = await post(
            client, f"/review-items/{item.id}/disposition", tenant_id, {"disposition": "rejected"}
        )

        assert second.status_code == 409

    async def test_edited_without_corrected_values_is_422(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        response = await post(
            client, f"/review-items/{item.id}/disposition", tenant_id, {"disposition": "edited"}
        )

        assert response.status_code == 422

    async def test_approval_carrying_corrected_values_is_422(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        response = await post(
            client,
            f"/review-items/{item.id}/disposition",
            tenant_id,
            {"disposition": "approved", "corrected_values": {"description": "x"}},
        )

        assert response.status_code == 422

    async def test_unknown_or_foreign_item_is_404(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        foreign = await post(
            client,
            f"/review-items/{item.id}/disposition",
            uuid.uuid4(),
            {"disposition": "approved"},
        )
        missing = await post(
            client,
            f"/review-items/{uuid.uuid4()}/disposition",
            tenant_id,
            {"disposition": "approved"},
        )

        assert foreign.status_code == 404
        assert missing.status_code == 404

    async def test_resolution_writes_an_audit_row(self, client: AsyncClient) -> None:
        tenant_id = uuid.uuid4()
        item = await make_item(tenant_id)
        await seed([item])

        response = await post(
            client,
            f"/review-items/{item.id}/disposition",
            tenant_id,
            {"disposition": "edited", "corrected_values": {"description": "corrected"}},
        )

        assert response.status_code == 200
        sessionmaker = db.get_sessionmaker()
        async with sessionmaker() as session:
            rows = (
                (await session.execute(select(AuditLog).where(AuditLog.tenant_id == tenant_id)))
                .scalars()
                .all()
            )
        assert [row.action for row in rows] == ["review_item.resolve"]
        row = rows[0]
        assert row.resource_type == "review_item"
        assert row.resource_id == item.id
        assert row.request_id == response.headers["x-request-id"]
        assert row.detail == {"disposition": "edited", "source": "extraction"}
