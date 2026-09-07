"""Review queue (W5·A): routing low-confidence LLM output to human review.

Workers call route_for_review after a job completes; the reviewer API calls
list/get/resolve. The state machine is flat — pending → approved | edited |
rejected (docs/w5-decisions.md): every resolution is terminal, so there are
no re-entry loops, and `edited` captures corrected values at resolution time.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.audit_log as audit_repo
import app.repositories.review_items as review_items_repo
from app.models.review_item import ReviewItem, ReviewItemSource, ReviewItemStatus
from app.request_context import current_actor, current_request_id

logger = logging.getLogger(__name__)


class ReviewItemNotFoundError(Exception):
    def __init__(self, item_id: uuid.UUID) -> None:
        self.item_id = item_id
        super().__init__(f"review item {item_id} not found")


class ReviewItemAlreadyResolvedError(Exception):
    """A resolved item is terminal: pending → approved | edited | rejected
    with no re-entry, so acting on it again is a conflict. The pendency
    guard lives in the UPDATE itself, so this also covers a resolution
    racing this one."""

    def __init__(self, item_id: uuid.UUID) -> None:
        self.item_id = item_id
        super().__init__(f"review item {item_id} is already resolved")


# One item under review: (item_type, wire-shaped payload, model confidence).
# A type alias, not a model — the payload shape differs per item_type and the
# worker already holds validated data.
ReviewCandidate = tuple[str, dict[str, Any], float]


def below_threshold(confidence: float, threshold: float) -> bool:
    """The routing rule: confidence falls strictly below the threshold.
    Exactly-at-threshold output is accepted."""
    return confidence < threshold


async def route_for_review(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    source: ReviewItemSource,
    document_id: uuid.UUID,
    job_id: uuid.UUID,
    candidates: list[ReviewCandidate],
    threshold: float,
) -> int:
    """Persist the below-threshold candidates as pending Review Items.

    Workers call this after marking a job completed — routing is additive:
    the job's own result ships regardless, and the low-confidence subset
    lands in the queue for a human. Returns the number of items created.
    """
    routed = [c for c in candidates if below_threshold(c[2], threshold)]
    if not routed:
        return 0
    rows = await review_items_repo.create_many(
        session,
        tenant_id=tenant_id,
        source=source,
        document_id=document_id,
        job_id=job_id,
        items=routed,
    )
    logger.info(
        "review items created tenant=%s source=%s job=%s count=%d threshold=%.2f",
        tenant_id,
        source.value,
        job_id,
        len(rows),
        threshold,
    )
    return len(rows)


async def list_review_items(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: ReviewItemStatus | None = None,
) -> list[ReviewItem]:
    return await review_items_repo.list_for_tenant(session, tenant_id=tenant_id, status=status)


async def get_review_item(
    session: AsyncSession, *, tenant_id: uuid.UUID, item_id: uuid.UUID
) -> ReviewItem:
    """Fetch one review item scoped to the tenant.

    Raises ReviewItemNotFoundError for unknown ids and other tenants' rows alike.
    """
    item = await review_items_repo.find_by_id(session, tenant_id=tenant_id, item_id=item_id)
    if item is None:
        raise ReviewItemNotFoundError(item_id)
    return item


async def resolve_review_item(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    item_id: uuid.UUID,
    disposition: ReviewItemStatus,
    corrected_values: dict[str, Any] | None,
) -> ReviewItem:
    """Resolve one pending item with a Disposition (approved / edited /
    rejected); `edited` carries corrected values, the others carry none —
    the schema enforces that pairing, the repository's pendency guard
    enforces terminality atomically.

    Raises ReviewItemNotFoundError for unknown ids and other tenants' rows
    alike, ReviewItemAlreadyResolvedError for a second resolution.
    """
    # Fetch first so an unknown/foreign item is a 404, not a silent no-op.
    await get_review_item(session, tenant_id=tenant_id, item_id=item_id)
    resolved = await review_items_repo.resolve(
        session,
        tenant_id=tenant_id,
        item_id=item_id,
        status=disposition,
        corrected_values=corrected_values,
    )
    if resolved is None:
        raise ReviewItemAlreadyResolvedError(item_id)
    logger.info(
        "review item resolved tenant=%s item=%s disposition=%s",
        tenant_id,
        item_id,
        disposition.value,
    )
    await audit_repo.record(
        session,
        tenant_id=tenant_id,
        request_id=current_request_id(),
        action="review_item.resolve",
        actor=current_actor(),
        resource_type="review_item",
        resource_id=item_id,
        detail={"disposition": disposition.value, "source": resolved.source.value},
    )
    return resolved
