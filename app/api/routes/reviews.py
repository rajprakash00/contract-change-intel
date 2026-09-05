"""HTTP adapter for the Review Queue: parse request, call service, return schema.

The reviewer surface (W5·A): list the queue, inspect one item, resolve it
with a Disposition. Resolution is terminal — a second resolution is a 409,
mapped by the app-wide error table, never a per-route try/except.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

import app.services.review_queue as review_service
from app.api.deps import SessionDep, TenantId
from app.models.review_item import ReviewItemStatus
from app.schemas.reviews import (
    ReviewDispositionCreate,
    ReviewItemRead,
    ReviewItemsResponse,
)

router = APIRouter(tags=["reviews"])

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, str]] = {
    404: {"description": "no such resource for this tenant"}
}
_CONFLICT_RESPONSE: dict[int | str, dict[str, str]] = {
    409: {"description": "the item is already resolved"}
}


@router.get("/review-items", response_model=ReviewItemsResponse)
async def get_review_items(
    session: SessionDep,
    tenant_id: TenantId,
    review_status: Annotated[
        str | None, Query(alias="status", pattern="^(pending|approved|edited|rejected)$")
    ] = None,
) -> ReviewItemsResponse:
    items = await review_service.list_review_items(
        session,
        tenant_id=tenant_id,
        status=ReviewItemStatus(review_status) if review_status else None,
    )
    return ReviewItemsResponse(items=[ReviewItemRead.model_validate(item) for item in items])


@router.get(
    "/review-items/{item_id}",
    response_model=ReviewItemRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def get_review_item(
    session: SessionDep,
    item_id: uuid.UUID,
    tenant_id: TenantId,
) -> ReviewItemRead:
    item = await review_service.get_review_item(session, tenant_id=tenant_id, item_id=item_id)
    return ReviewItemRead.model_validate(item)


@router.post(
    "/review-items/{item_id}/disposition",
    response_model=ReviewItemRead,
    responses=_NOT_FOUND_RESPONSE | _CONFLICT_RESPONSE,
)
async def post_review_item_disposition(
    session: SessionDep,
    item_id: uuid.UUID,
    request: ReviewDispositionCreate,
    tenant_id: TenantId,
) -> ReviewItemRead:
    item = await review_service.resolve_review_item(
        session,
        tenant_id=tenant_id,
        item_id=item_id,
        disposition=ReviewItemStatus(request.disposition),
        corrected_values=request.corrected_values,
    )
    return ReviewItemRead.model_validate(item)
