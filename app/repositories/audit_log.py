"""Insert-only writes + tenant-scoped reads for the append-only audit trail."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    request_id: str,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            request_id=request_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )
    )
    await session.commit()


async def list_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str | None = None,
    limit: int,
) -> list[AuditLog]:
    """The tenant's trail, chronological: an audit log reads as a timeline,
    oldest first, and the limit truncates from the newest end."""
    query = select(AuditLog).where(AuditLog.tenant_id == tenant_id)
    if action is not None:
        query = query.where(AuditLog.action == action)
    result = await session.execute(
        query.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(limit)
    )
    return list(result.scalars().all())
