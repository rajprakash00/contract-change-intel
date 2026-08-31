import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
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


async def find_by_id(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> Document | None:
    result = await session.execute(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_page(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int, offset: int
) -> Sequence[Document]:
    # Newest first; id breaks ties so equal-timestamp rows keep a stable order.
    result = await session.execute(
        select(Document)
        .where(Document.tenant_id == tenant_id)
        .order_by(Document.created_at.desc(), Document.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


async def count_for_tenant(session: AsyncSession, *, tenant_id: uuid.UUID) -> int:
    result = await session.execute(
        select(func.count()).select_from(Document).where(Document.tenant_id == tenant_id)
    )
    return result.scalar_one()


async def set_status(session: AsyncSession, document: Document, status: DocumentStatus) -> Document:
    """Flip a document's lifecycle status (worker-side terminal ingestion states)."""
    document.status = status
    await session.commit()
    await session.refresh(document)
    return document


async def delete(session: AsyncSession, document: Document) -> None:
    await session.delete(document)
    await session.commit()
