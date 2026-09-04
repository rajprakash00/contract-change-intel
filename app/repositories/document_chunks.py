import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.document_chunk import DocumentChunk


async def count_for_document(session: AsyncSession, *, document_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
    )
    return result.scalar_one()


async def replace_with_embeddings(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    chunks: list[tuple[str, int, int]],
    embeddings: list[list[float]],
) -> list[DocumentChunk]:
    """Write one row per chunk (ordinal = position, 0-based), replacing any
    previous rows for the document — a re-run must not accumulate stale chunks.

    `chunks` are (text, char_start, char_end) into the document's parsed text.
    Flushes but does not commit: text and chunks belong to one transaction, so
    the caller commits once both tables are written (citation offsets must
    never misalign across a crash).
    """
    if len(chunks) != len(embeddings):
        raise ValueError("every chunk needs exactly one embedding vector")
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    rows = [
        DocumentChunk(
            tenant_id=tenant_id,
            document_id=document_id,
            ordinal=ordinal,
            text=text,
            char_start=char_start,
            char_end=char_end,
            embedding=embedding,
        )
        for ordinal, ((text, char_start, char_end), embedding) in enumerate(
            zip(chunks, embeddings, strict=True)
        )
    ]
    session.add_all(rows)
    await session.flush()
    return rows


async def rank_by_similarity(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    embedding: list[float],
    limit: int,
    document_id: uuid.UUID | None = None,
) -> list[tuple[DocumentChunk, Document]]:
    """The vector half of hybrid search (ADR-006): nearest chunks by cosine
    distance, best first, joined with their owning document. Tenant-scoped;
    chunks without embeddings (never written by the pipeline) are skipped.
    `document_id` narrows the ranking to one document's chunks — the
    document-scoped variant impact mapping needs (W4·D).
    """
    filters = [DocumentChunk.tenant_id == tenant_id, DocumentChunk.embedding.is_not(None)]
    if document_id is not None:
        filters.append(DocumentChunk.document_id == document_id)
    result = await session.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*filters)
        .order_by(DocumentChunk.embedding.cosine_distance(embedding))
        .limit(limit)
    )
    return [(chunk, document) for chunk, document in result.all()]


async def rank_by_full_text(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    limit: int,
    document_id: uuid.UUID | None = None,
) -> list[tuple[DocumentChunk, Document]]:
    """The full-text half of hybrid search (ADR-006): chunks whose generated
    tsvector matches the query's plain tsquery, best ts_rank first. Only
    exact/stemmed tokens match here; paraphrase recall is the vector half's job.
    `document_id` narrows the ranking to one document's chunks (W4·D).
    """
    tsquery = func.plainto_tsquery("english", query)
    filters = [DocumentChunk.tenant_id == tenant_id, DocumentChunk.tsv.op("@@")(tsquery)]
    if document_id is not None:
        filters.append(DocumentChunk.document_id == document_id)
    result = await session.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*filters)
        .order_by(func.ts_rank(DocumentChunk.tsv, tsquery).desc())
        .limit(limit)
    )
    return [(chunk, document) for chunk, document in result.all()]
