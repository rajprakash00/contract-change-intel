import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
