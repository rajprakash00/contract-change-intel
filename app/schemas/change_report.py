import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models.change_report_job import ChangeReportJobStatus


class ChangeReportCreate(BaseModel):
    """POST /agreements/{id}/change-report body: names the amendment to diff
    against the agreement in the path."""

    amendment_document_id: uuid.UUID


class ChangeReportJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    base_document_id: uuid.UUID
    amended_document_id: uuid.UUID
    status: ChangeReportJobStatus
    # Wire-shaped report when completed ({"changes": [...]}).
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime


class ChangePrerequisiteDetail(BaseModel):
    """409 detail when a change report is requested before both versions have
    completed ingestion and extraction jobs: the document, the missing kind,
    and its latest job (null when never run) — the first gap in
    base-ingestion → base-extraction → amendment-ingestion →
    amendment-extraction order."""

    document_id: uuid.UUID
    kind: Literal["ingestion", "extraction"]
    job_id: uuid.UUID | None
