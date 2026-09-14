"""HTTP adapter for the LLM spend surface (issue #30): the tenant's usage
accounting, aggregated per job kind or per job. Admin-only — spend is a
cost-control fact, not a working document.
"""

from typing import Literal

from fastapi import APIRouter

import app.services.usage as usage_service
from app.api.deps import AdminPrincipal, SessionDep
from app.schemas.usage import UsageSpendResponse, UsageSpendRow

router = APIRouter(tags=["usage"])


@router.get("/usage/spend", response_model=UsageSpendResponse)
async def get_usage_spend(
    session: SessionDep,
    principal: AdminPrincipal,
    group_by: Literal["job_type", "job"] = "job_type",
) -> UsageSpendResponse:
    report = await usage_service.spend(session, tenant_id=principal.tenant_id, group_by=group_by)
    return UsageSpendResponse(
        rows=[UsageSpendRow.model_validate(row, from_attributes=True) for row in report.rows],
        total=UsageSpendRow.model_validate(report.total, from_attributes=True),
    )
