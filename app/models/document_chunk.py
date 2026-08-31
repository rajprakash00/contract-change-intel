"""Chunks: the retrieved-and-cited unit (CONTEXT.md), one row per chunk.

`char_start`/`char_end` index into the owning document's DocumentText.text;
`text` always equals that substring, so citations need no second coordinate
system. `embedding` is filled by the ingestion worker (W3); `tsv` is a
Postgres-generated column feeding the full-text half of hybrid search
(ADR-006).
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small (ADR-006)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_tenant_id", "tenant_id"),
        # HNSW parameters stay at library defaults until evals justify tuning.
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_document_chunks_tsv_gin", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    # Position of the chunk within its document, 0-based, dense.
    ordinal: Mapped[int] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column()
    char_end: Mapped[int] = mapped_column()
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
