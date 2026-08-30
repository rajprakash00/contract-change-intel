import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.extraction_job import ExtractionJobStatus


class ExtractionJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    document_id: uuid.UUID
    status: ExtractionJobStatus
    # Wire-shaped extraction payload when completed ({"obligations": [...]}).
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
