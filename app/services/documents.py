"""Document upload flow: validation, hashing, storage, persistence.

Business rules live here; routers translate the module's exceptions into HTTP
responses. The service depends on repository + storage functions only — no
FastAPI types cross this boundary.
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.documents as documents_repo
import app.storage.local as local_storage
from app.models.document import Document

logger = logging.getLogger(__name__)

# Parsing pipeline (week 3) defines what we can actually process.
ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    }
)

_READ_CHUNK_SIZE = 1024 * 1024


class MimeNotAllowedError(Exception):
    def __init__(self, content_type: str | None) -> None:
        self.content_type = content_type
        super().__init__(f"unsupported media type {content_type!r}")


class UploadTooLargeError(Exception):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"upload exceeds limit of {max_bytes} bytes")


class DocumentAlreadyExistsError(Exception):
    def __init__(self, existing_id: uuid.UUID | None = None) -> None:
        self.existing_id = existing_id
        super().__init__("document already exists")


async def _read_upload(
    read: Callable[[int], Awaitable[bytes]], max_bytes: int
) -> tuple[str, bytes]:
    """Consume the upload stream once: enforce the size cap and hash in one pass."""
    hasher = hashlib.sha256()
    parts: list[bytes] = []
    total = 0
    while chunk := await read(_READ_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise UploadTooLargeError(max_bytes)
        hasher.update(chunk)
        parts.append(chunk)
    return hasher.hexdigest(), b"".join(parts)


async def upload_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    filename: str | None,
    content_type: str | None,
    read: Callable[[int], Awaitable[bytes]],
    data_dir: str,
    max_bytes: int,
) -> Document:
    """Validate, dedupe-check, store to disk, then persist a row.

    Raises MimeNotAllowedError, UploadTooLargeError, DocumentAlreadyExistsError.
    """
    if content_type not in ALLOWED_MIME_TYPES:
        raise MimeNotAllowedError(content_type)

    sha256, content = await _read_upload(read, max_bytes)

    existing = await documents_repo.find_by_sha256(session, tenant_id=tenant_id, sha256=sha256)
    if existing is not None:
        raise DocumentAlreadyExistsError(existing.id)

    # Disk IO is blocking; keep it off the event loop.
    await asyncio.to_thread(local_storage.save_document, data_dir, tenant_id, sha256, content)

    try:
        document = await documents_repo.create(
            session,
            tenant_id=tenant_id,
            filename=filename or "untitled",
            mime_type=content_type or "application/octet-stream",
            sha256=sha256,
        )
    except IntegrityError:
        # Lost a race against a concurrent upload of identical bytes within this
        # tenant. The stored file is content-addressed, so leaving it is correct.
        await session.rollback()
        raced = await documents_repo.find_by_sha256(session, tenant_id=tenant_id, sha256=sha256)
        logger.info(
            "duplicate upload race tenant=%s sha=%s winner=%s",
            tenant_id,
            sha256,
            raced.id if raced else None,
        )
        raise DocumentAlreadyExistsError(raced.id if raced else None) from None

    logger.info(
        "document uploaded tenant=%s document=%s sha=%s bytes=%d",
        document.tenant_id,
        document.id,
        document.sha256,
        len(content),
    )
    return document
