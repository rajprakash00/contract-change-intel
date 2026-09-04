"""Change report jobs: the third sibling of the ADR-004 job family.

A job diffs one document version against the amendment it names and asks
the LLM for per-Change explanations in one structured call — both happen
in the worker, never the request path. Claim/lease semantics are identical
to the other job tables (app/repositories/job_claims.py).
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChangeReportJobStatus(enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ChangeReportJob(Base):
    __tablename__ = "change_report_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    # The version amended away from, and the amendment named by the caller:
    # Change Reports diff exactly these two documents, never collapsed chains
    # (docs/w4-decisions.md).
    base_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    amended_document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[ChangeReportJobStatus] = mapped_column(
        Enum(ChangeReportJobStatus, name="change_report_job_status", native_enum=True),
        default=ChangeReportJobStatus.queued,
    )
    # Wire-shaped report once completed: {"changes": [...]}.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(1024))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
