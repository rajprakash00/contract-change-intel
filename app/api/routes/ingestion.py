"""HTTP adapter for ingestion endpoints: parse request, call service, return schema.

Enqueue returns 202 immediately: parsing and embedding happen in the worker
process, never in the request path. Status is polled via
GET /ingestion-jobs/{id}. Re-enqueueing while a job is queued/running is a
409 carrying the blocking job's id; from a terminal state it starts a new run.
"""

import uuid

from fastapi import APIRouter, status

import app.services.ingestion as ingestion_service
from app.api.deps import SessionDep, TenantId
from app.schemas.ingestion import IngestionJobRead

router = APIRouter(tags=["ingestion"])

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, str]] = {
    404: {"description": "no such resource for this tenant"}
}


@router.post(
    "/documents/{document_id}/ingestion",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestionJobRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def post_document_ingestion(
    session: SessionDep,
    document_id: uuid.UUID,
    tenant_id: TenantId,
) -> IngestionJobRead:
    job = await ingestion_service.enqueue_ingestion(
        session, tenant_id=tenant_id, document_id=document_id
    )
    return IngestionJobRead.model_validate(job)


@router.get(
    "/ingestion-jobs/{job_id}",
    response_model=IngestionJobRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def get_ingestion_job(
    session: SessionDep,
    job_id: uuid.UUID,
    tenant_id: TenantId,
) -> IngestionJobRead:
    job = await ingestion_service.get_ingestion_job(session, tenant_id=tenant_id, job_id=job_id)
    return IngestionJobRead.model_validate(job)
