"""HTTP adapter for the audit trail read surface (W5·B): the tenant's
chronological, append-only log of the mutations its services performed.
"""

from typing import Annotated

from fastapi import APIRouter, Query

import app.services.audit as audit_service
from app.api.deps import PrincipalDep, SessionDep
from app.schemas.audit import AuditEntriesResponse, AuditEntryRead

router = APIRouter(tags=["audit"])


@router.get("/audit-log", response_model=AuditEntriesResponse)
async def get_audit_log(
    session: SessionDep,
    principal: PrincipalDep,
    action: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> AuditEntriesResponse:
    entries = await audit_service.list_audit_entries(
        session, tenant_id=principal.tenant_id, action=action, limit=limit
    )
    return AuditEntriesResponse(items=[AuditEntryRead.model_validate(e) for e in entries])
