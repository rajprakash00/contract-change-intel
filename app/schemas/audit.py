import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    actor: str | None
    request_id: str
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    detail: dict[str, Any] | None
    created_at: datetime


class AuditEntriesResponse(BaseModel):
    items: list[AuditEntryRead]
