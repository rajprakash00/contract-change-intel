import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.ingestion_job import IngestionJobStatus


class IngestionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    status: IngestionJobStatus
    # Wire-shaped run summary when completed ({"chunk_count": n}).
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class JobConflictDetail(BaseModel):
    """409 detail shared by both job surfaces: the id of the job in the way."""

    existing_job_id: uuid.UUID
