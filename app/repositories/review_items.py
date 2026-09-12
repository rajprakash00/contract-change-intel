import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.review_item import ReviewItem, ReviewItemSource, ReviewItemStatus


async def create_many(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: ReviewItemSource,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
    items: list[tuple[str, dict, float]],
) -> list[ReviewItem]:
    """Insert pending Review Items in one commit.

    `items` holds (item_type, payload, confidence) triples — the caller has
    already applied the threshold rule; this is persistence only.
    """
    rows = [
        ReviewItem(
            tenant_id=tenant_id,
            source=source,
            item_type=item_type,
            document_id=document_id,
            job_id=job_id,
            payload=payload,
            confidence=confidence,
        )
        for item_type, payload, confidence in items
    ]
    session.add_all(rows)
    await session.commit()
    return rows


async def find_by_id(
    session: AsyncSession, *, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> ReviewItem | None:
    result = await session.execute(
        select(ReviewItem).where(ReviewItem.id == item_id, ReviewItem.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: ReviewItemStatus | None = None,
) -> list[ReviewItem]:
    """Oldest first: the queue reads as triage order, not recency."""
    query = select(ReviewItem).where(ReviewItem.tenant_id == tenant_id)
    if status is not None:
        query = query.where(ReviewItem.status == status)
    result = await session.execute(query.order_by(ReviewItem.created_at.asc(), ReviewItem.id.asc()))
    return list(result.scalars().all())


async def resolve(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    status: ReviewItemStatus,
    corrected_values: dict[str, Any] | None,
) -> ReviewItem | None:
    """Apply one Disposition, guarded on pendency.

    The WHERE clause makes the flat state machine atomic: a second
    resolution racing the first updates zero rows and returns None, so
    no re-entry is possible even under concurrency.
    """
    result = await session.execute(
        update(ReviewItem)
        .where(
            ReviewItem.id == item_id,
            ReviewItem.tenant_id == tenant_id,
            ReviewItem.status == ReviewItemStatus.pending,
        )
        .values(status=status, corrected_values=corrected_values, resolved_at=datetime.now(UTC))
        .returning(ReviewItem)
    )
    await session.commit()
    return result.scalar_one_or_none()


async def delete_for_document(session: AsyncSession, *, document_id: uuid.UUID) -> None:
    """Delete the Review Items concerning one document (extraction-sourced
    items). No commit: the document-delete sweep commits once at the end."""
    await session.execute(delete(ReviewItem).where(ReviewItem.document_id == document_id))


async def delete_for_jobs(session: AsyncSession, *, job_ids: Sequence[uuid.UUID]) -> None:
    """Delete the Review Items routed from the named jobs — the impact
    mappings that came from Change Reports about to be deleted. No commit:
    same sweep as above."""
    if not job_ids:
        return
    await session.execute(delete(ReviewItem).where(ReviewItem.job_id.in_(job_ids)))
