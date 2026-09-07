"""HTTP adapter for the Change Report surface: parse request, call service,
return schema.

POST /agreements/{id}/change-report names the amendment and returns 202
immediately: diffing and the LLM explanation call happen in the worker
process, never in the request path. Status is polled via
GET /change-report-jobs/{id}.
"""

import uuid

from fastapi import APIRouter, status

import app.services.change_report as change_report_service
from app.api.deps import AdminPrincipal, PrincipalDep, SessionDep
from app.schemas.change_report import ChangeReportCreate, ChangeReportJobRead

router = APIRouter(tags=["change-reports"])

_NOT_FOUND_RESPONSE: dict[int | str, dict[str, str]] = {
    404: {"description": "no such resource for this tenant"}
}


@router.post(
    "/agreements/{agreement_id}/change-report",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ChangeReportJobRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def post_agreement_change_report(
    session: SessionDep,
    agreement_id: uuid.UUID,
    request: ChangeReportCreate,
    principal: AdminPrincipal,
) -> ChangeReportJobRead:
    job = await change_report_service.enqueue_change_report(
        session,
        tenant_id=principal.tenant_id,
        base_document_id=agreement_id,
        amended_document_id=request.amendment_document_id,
    )
    return ChangeReportJobRead.model_validate(job)


@router.get(
    "/change-report-jobs/{job_id}",
    response_model=ChangeReportJobRead,
    responses=_NOT_FOUND_RESPONSE,
)
async def get_change_report_job(
    session: SessionDep,
    job_id: uuid.UUID,
    principal: PrincipalDep,
) -> ChangeReportJobRead:
    job = await change_report_service.get_change_report_job(
        session, tenant_id=principal.tenant_id, job_id=job_id
    )
    return ChangeReportJobRead.model_validate(job)
