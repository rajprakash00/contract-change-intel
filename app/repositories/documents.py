import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentStatus


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    filename: str,
    mime_type: str,
    sha256: str,
) -> Document:
    document = Document(
        tenant_id=tenant_id,
        filename=filename,
        mime_type=mime_type,
        sha256=sha256,
        status=DocumentStatus.uploaded,
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)
    return document


async def find_by_sha256(
    session: AsyncSession, *, tenant_id: uuid.UUID, sha256: str
) -> Document | None:
    result = await session.execute(
        select(Document).where(Document.tenant_id == tenant_id, Document.sha256 == sha256)
    )
    return result.scalar_one_or_none()
