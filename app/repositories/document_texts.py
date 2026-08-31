import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_text import DocumentText


async def find_by_document_id(
    session: AsyncSession, *, document_id: uuid.UUID
) -> DocumentText | None:
    result = await session.execute(
        select(DocumentText).where(DocumentText.document_id == document_id)
    )
    return result.scalar_one_or_none()


async def replace(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    text: str,
    page_map: list[dict[str, Any]],
) -> DocumentText:
    """Write the parsed text wholesale, replacing any previous row.

    Citation offsets are char positions into `text`, so a re-ingestion must
    never merge old and new rows — the re-run path is delete-then-insert.
    Flushes but does not commit: the caller commits text and chunks together
    so a crash can never leave new text beside old chunks.
    """
    await session.execute(delete(DocumentText).where(DocumentText.document_id == document_id))
    row = DocumentText(tenant_id=tenant_id, document_id=document_id, text=text, page_map=page_map)
    session.add(row)
    await session.flush()
    return row
