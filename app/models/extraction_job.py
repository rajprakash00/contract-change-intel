"""Extraction jobs: Postgres-backed background work (no Celery).

The API only ever enqueues a row; the LLM call happens in the worker process,
so no synchronous LLM call sits in the request path. Handlers are idempotent:
a job is claimed exactly once per pass via FOR UPDATE SKIP LOCKED, and only
`queued` rows are ever picked up.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ExtractionJobStatus(enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    status: Mapped[ExtractionJobStatus] = mapped_column(
        Enum(ExtractionJobStatus, name="extraction_job_status", native_enum=True),
        default=ExtractionJobStatus.queued,
    )
    # Wire-shaped extraction result ({"obligations": [...]}) once completed.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Human-readable failure reason when status is failed; no stack traces.
    error: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
