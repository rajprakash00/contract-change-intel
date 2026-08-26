import uuid

from pydantic import BaseModel, ConfigDict

from app.models.document import DocumentStatus


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    mime_type: str
    sha256: str
    status: DocumentStatus


class DocumentConflictDetail(BaseModel):
    existing_id: uuid.UUID
