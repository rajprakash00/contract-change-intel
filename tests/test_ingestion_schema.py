"""Integration tests for the W3 ingestion schema (real Postgres).

Locks the pieces W3·B/W3·C build on: pgvector round-trips at 1536 dims, the
tsvector generated column populates from chunk text, and the ingestion job
row carries the ADR-004 lease columns from creation.
"""

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app.config import get_settings
from app.models.document import Document
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.document_text import DocumentText
from app.models.ingestion_job import IngestionJob, IngestionJobStatus

# Unit-length-ish vector; values only matter for the round-trip.
_FAKE_EMBEDDING = [0.001 * (i % 10) for i in range(EMBEDDING_DIMENSIONS)]


@pytest.fixture(autouse=True)
async def engine() -> AsyncIterator[None]:
    db.init_engine(get_settings().database_url)
    yield
    await db.dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with db.get_sessionmaker()() as s:
        await s.execute(delete(DocumentChunk))
        await s.execute(delete(DocumentText))
        await s.execute(delete(IngestionJob))
        await s.execute(delete(Document))
        await s.commit()


async def make_document(session: AsyncSession) -> Document:
    document = Document(
        tenant_id=uuid.uuid4(),
        filename="msa.pdf",
        mime_type="application/pdf",
        sha256=uuid.uuid4().hex * 2,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def test_vector_round_trips_at_embedding_dimensions() -> None:
    async with db.get_sessionmaker()() as s:
        document = await make_document(s)
        s.add(
            DocumentChunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                ordinal=0,
                text="The supplier shall deliver goods.",
                char_start=0,
                char_end=32,
                embedding=_FAKE_EMBEDDING,
            )
        )
        await s.commit()

        row = await s.execute(select(DocumentChunk).where(DocumentChunk.document_id == document.id))

    chunk = row.scalar_one()
    assert chunk.embedding is not None
    assert len(chunk.embedding) == EMBEDDING_DIMENSIONS
    assert chunk.embedding[0] == pytest.approx(_FAKE_EMBEDDING[0])


async def test_tsvector_is_generated_from_chunk_text() -> None:
    async with db.get_sessionmaker()() as s:
        document = await make_document(s)
        s.add(
            DocumentChunk(
                tenant_id=document.tenant_id,
                document_id=document.id,
                ordinal=0,
                text="The supplier shall indemnify the customer.",
                char_start=0,
                char_end=42,
            )
        )
        await s.commit()

        hits = await s.execute(
            text(
                "SELECT count(*) FROM document_chunks "
                "WHERE tsv @@ to_tsquery('english', 'indemnify') "
                "AND document_id = :document_id"
            ),
            {"document_id": document.id},
        )

    assert hits.scalar_one() == 1


async def test_ingestion_job_defaults_carry_lease_columns() -> None:
    async with db.get_sessionmaker()() as s:
        document = await make_document(s)
        job = IngestionJob(tenant_id=document.tenant_id, document_id=document.id)
        s.add(job)
        await s.commit()
        await s.refresh(job)

        stored = await s.get(IngestionJob, job.id)

    assert stored is not None
    assert stored.status is IngestionJobStatus.queued
    assert stored.attempts == 0
    assert stored.lease_expires_at is None
    assert stored.result is None
    assert stored.error is None
