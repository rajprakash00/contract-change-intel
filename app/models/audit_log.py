import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """Append-only audit trail.

    Rows are written once when a mutation succeeds and are never updated or
    deleted by application code; retention is a separate concern.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # Who acted: the token subject for API-driven mutations (W5·C). Null for
    # rows written before auth landed and for service-direct callers (evals).
    actor: Mapped[str | None] = mapped_column(String(255))
    # Correlates the audit row with the API call that produced it ('' if none).
    request_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))  # e.g. document.upload
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID | None]
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
