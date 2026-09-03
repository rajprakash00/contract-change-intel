import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentStatus(enum.Enum):
    uploaded = "uploaded"
    parsed = "parsed"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        # Same bytes may only be uploaded once per tenant; dedupe key.
        UniqueConstraint("tenant_id", "sha256", name="uq_documents_tenant_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    filename: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64))
    # W4·B amendment model: the document this one amends, if any. RESTRICT
    # keeps deletes explicit — a parent with surviving amendments cannot go.
    amends_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", native_enum=True),
        default=DocumentStatus.uploaded,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
