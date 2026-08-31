"""Parsed text of a document: the char-offset coordinate system citations use.

One row per ingested document. Citation spans everywhere else (chunks,
obligations) are char offsets into `text`, so re-parsing must reproduce it
byte-for-byte — the re-run path replaces the row wholesale.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DocumentText(Base):
    __tablename__ = "document_texts"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    text: Mapped[str] = mapped_column(Text)
    # Page boundaries as char offsets into `text`:
    # [{"page": 1, "start": 0, "end": 1200}, ...]. Empty for formats with no
    # page concept (DOCX renders pages at print time, plain text has none).
    page_map: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
