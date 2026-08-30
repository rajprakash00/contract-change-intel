"""HTTP adapter for extraction endpoints: parse request, call service, return schema.

Enqueue returns 202 immediately: the LLM call happens in the worker process,
never in the request path. Status is polled via GET /extraction-jobs/{id}.
"""

import uuid

from fastapi import APIRouter, status

import app.services.extraction as extraction_service
from app.api.deps import SessionDep, TenantId
from app.schemas.extraction import ExtractionJobRead

router = APIRouter(tags=["extraction"])

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, str]] = {
    404: {"description": "no such resource for this tenant"}
}


@router.post(
    "/documents/{document_id}/extraction",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ExtractionJobRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def post_document_extraction(
    session: SessionDep,
    document_id: uuid.UUID,
    tenant_id: TenantId,
) -> ExtractionJobRead:
    job = await extraction_service.enqueue_extraction(
        session, tenant_id=tenant_id, document_id=document_id
    )
    return ExtractionJobRead.model_validate(job)


@router.get(
    "/extraction-jobs/{job_id}",
    response_model=ExtractionJobRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def get_extraction_job(
    session: SessionDep,
    job_id: uuid.UUID,
    tenant_id: TenantId,
) -> ExtractionJobRead:
    job = await extraction_service.get_extraction_job(session, tenant_id=tenant_id, job_id=job_id)
    return ExtractionJobRead.model_validate(job)
