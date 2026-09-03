"""Document flows: validation, hashing, storage, persistence, audit.

Business rules live here; routers translate the module's exceptions into HTTP
responses. The service depends on repository + storage functions only — no
FastAPI types cross this boundary.
"""

import asyncio
import hashlib
import io
import logging
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.audit_log as audit_repo
import app.repositories.documents as documents_repo
import app.storage.local as local_storage
from app.models.document import Document
from app.request_context import current_request_id

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

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 100


class MimeNotAllowedError(Exception):
    def __init__(self, content_type: str | None, sniffed: str | None = None) -> None:
        self.content_type = content_type
        self.sniffed = sniffed
        super().__init__(f"unsupported media type {content_type!r}")


class UploadTooLargeError(Exception):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        super().__init__(f"upload exceeds limit of {max_bytes} bytes")


class DocumentAlreadyExistsError(Exception):
    def __init__(self, existing_id: uuid.UUID | None = None) -> None:
        self.existing_id = existing_id
        super().__init__("document already exists")


class DocumentNotFoundError(Exception):
    def __init__(self, document_id: uuid.UUID) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} not found")


class DocumentHasAmendmentsError(Exception):
    def __init__(self, document_id: uuid.UUID) -> None:
        self.document_id = document_id
        super().__init__(f"document {document_id} has amendments; delete them first")


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


_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sniff_mime(content: bytes) -> str | None:
    """Sniff magic bytes of doc.
    PDF by prefix; DOCX as a ZIP package carrying Word parts; text when the
    bytes decode as UTF-8 without NULs. Anything else reads as unknown.
    """
    if not content:
        return None
    if content.startswith(_PDF_MAGIC):
        return "application/pdf"
    if content.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as bundle:
                names = bundle.namelist()
        except zipfile.BadZipFile:
            return None
        if "[Content_Types].xml" in names and any(n.startswith("word/") for n in names):
            return _DOCX_MIME
        return None
    if b"\x00" in content:
        return None
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return "text/plain"


async def upload_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    filename: str | None,
    content_type: str | None,
    read: Callable[[int], Awaitable[bytes]],
    data_dir: str,
    max_bytes: int,
    amends_document_id: uuid.UUID | None = None,
) -> Document:
    """Validate, dedupe-check, sniff, store to disk, then persist.

    Raises MimeNotAllowedError, UploadTooLargeError, DocumentAlreadyExistsError,
    DocumentNotFoundError (unknown or cross-tenant amends_document_id).
    """
    if content_type not in ALLOWED_MIME_TYPES:
        raise MimeNotAllowedError(content_type)

    sha256, content = await _read_upload(read, max_bytes)

    # Sniff and match declared doc types.
    sniffed = sniff_mime(content)
    if sniffed != content_type:
        raise MimeNotAllowedError(content_type, sniffed=sniffed)

    # Parent check runs before the dedupe so a bad reference surfaces as 404
    # even when the bytes would also have conflicted. A parent is only
    # linkable from its own tenant; unknown and foreign parents read alike.
    # Self-reference (409 per the spec) is unreachable by construction: ids
    # are server-generated, so a caller can never name the document it is
    # creating — the DB self-FK would reject it as missing anyway.
    if amends_document_id is not None:
        parent = await documents_repo.find_by_id(
            session, tenant_id=tenant_id, document_id=amends_document_id
        )
        if parent is None:
            raise DocumentNotFoundError(amends_document_id)

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
            amends_document_id=amends_document_id,
        )
    except IntegrityError:
        # Concurrent upload by tenant
        # The stored file is content-addressed, so leaving it is correct.
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
    detail: dict[str, object] = {
        "filename": document.filename,
        "sha256": document.sha256,
        "mime_type": document.mime_type,
        "size_bytes": len(content),
    }
    if amends_document_id is not None:
        detail["amends_document_id"] = str(amends_document_id)
    await audit_repo.record(
        session,
        tenant_id=document.tenant_id,
        request_id=current_request_id(),
        action="document.upload",
        resource_type="document",
        resource_id=document.id,
        detail=detail,
    )
    return document


async def get_document(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    """Fetch one document scoped to the tenant.

    Raises DocumentNotFoundError for unknown ids and other tenants' rows alike.
    """
    document = await documents_repo.find_by_id(
        session, tenant_id=tenant_id, document_id=document_id
    )
    if document is None:
        raise DocumentNotFoundError(document_id)
    return document


async def list_documents(
    session: AsyncSession, *, tenant_id: uuid.UUID, limit: int, offset: int
) -> tuple[Sequence[Document], int]:
    """One page of the tenant's documents (newest first) plus the total count."""
    items = await documents_repo.list_page(session, tenant_id=tenant_id, limit=limit, offset=offset)
    total = await documents_repo.count_for_tenant(session, tenant_id=tenant_id)
    return items, total


async def resolve_document_file(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID, data_dir: str
) -> tuple[Document, Path]:
    """Row + on-disk path for download; both halves must exist or it reads as 404."""
    document = await get_document(session, tenant_id=tenant_id, document_id=document_id)
    path = local_storage.document_path(data_dir, tenant_id, document.sha256)
    if not await asyncio.to_thread(path.is_file):
        # Row without bytes is an integrity gap; doc not found
        logger.warning(
            "document row missing stored file tenant=%s document=%s sha=%s",
            tenant_id,
            document.id,
            document.sha256,
        )
        raise DocumentNotFoundError(document_id)
    return document, path


async def delete_document(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID, data_dir: str
) -> None:
    """Delete the row, then remove the stored file.

    Row first: a crash between the two steps leaves at worst an orphan file,
    never a row pointing at missing bytes. Raises DocumentNotFoundError,
    DocumentHasAmendmentsError.
    """
    document = await get_document(session, tenant_id=tenant_id, document_id=document_id)
    # The FK is RESTRICT; naming the conflict here keeps the 500 off the wire
    # and the chain deletion explicit (leaf first).
    if await documents_repo.has_amendments(session, document_id=document_id):
        raise DocumentHasAmendmentsError(document_id)
    await documents_repo.delete(session, document)

    removed = await asyncio.to_thread(
        local_storage.delete_document, data_dir, tenant_id, document.sha256
    )
    if not removed:
        logger.warning(
            "deleted row had no stored file tenant=%s document=%s sha=%s",
            tenant_id,
            document.id,
            document.sha256,
        )
    logger.info(
        "document deleted tenant=%s document=%s sha=%s", tenant_id, document.id, document.sha256
    )
    await audit_repo.record(
        session,
        tenant_id=tenant_id,
        request_id=current_request_id(),
        action="document.delete",
        resource_type="document",
        resource_id=document.id,
        detail={"filename": document.filename, "sha256": document.sha256},
    )
