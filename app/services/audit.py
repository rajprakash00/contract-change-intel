"""Audit trail reads (W5·B): the tenant-scoped read API over the append-only
log the mutating services write.

Writes happen inside the owning services (document flows, job enqueues,
review resolutions); this service is the read side only — no retention
window yet, matching the open W5 item.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.audit_log as audit_repo
from app.models.audit_log import AuditLog


async def list_audit_entries(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str | None = None,
    limit: int,
) -> list[AuditLog]:
    """The tenant's own trail, chronological; `action` narrows it to one
    kind of mutating event."""
    return await audit_repo.list_for_tenant(
        session, tenant_id=tenant_id, action=action, limit=limit
    )
