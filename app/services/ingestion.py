"""Document ingestion: parse → chunk → embed → persist, on a job row (ADR-004).

The API only ever enqueues a queued row; run_next_ingestion_job is the
worker-side unit that claims one job, does the blocking parse via
asyncio.to_thread, embeds the chunks, and replaces the document's parsed
text + chunks delete-then-insert (so a re-run never accumulates stale rows).
Terminal states flip the document's status (parsed/failed), worker-side.

Third-party parsers raise an open set of exception types, and ADR-004's
"failures are data" contract means one bad job must not stop the worker
loop — so the handler converts every failure into a failed job row instead
of re-raising.
"""

import asyncio
import logging
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.audit_log as audit_repo
import app.repositories.document_chunks as document_chunks_repo
import app.repositories.document_texts as document_texts_repo
import app.repositories.documents as documents_repo
import app.repositories.ingestion_jobs as ingestion_jobs_repo
import app.services.usage as usage_service
import app.storage.local as local_storage
from app.llm.client import OpenAiClient, UsageSink
from app.models.document import Document, DocumentStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.llm_usage import UsageJobKind
from app.request_context import current_actor, current_request_id
from app.services.chunking import chunk_document
from app.services.documents import DocumentNotFoundError
from app.services.parsing import ParsedDocument, parse

logger = logging.getLogger(__name__)

# The embeddings endpoint accepts many inputs per call; batching keeps one
# request comfortably inside its limits for any real agreement.
_EMBED_BATCH = 128


class IngestionJobNotFoundError(Exception):
    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        super().__init__(f"ingestion job {job_id} not found")


class IngestionJobConflictError(Exception):
    def __init__(self, job_id: uuid.UUID) -> None:
        self.job_id = job_id
        super().__init__(f"ingestion job {job_id} is already queued or running")


async def enqueue_ingestion(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
) -> IngestionJob:
    """Queue ingestion for one document; the worker does parse/chunk/embed.

    Raises DocumentNotFoundError for unknown ids and other tenants' rows
    alike, and IngestionJobConflictError while a job for the document is
    still queued or running (re-run is allowed only from a terminal state).
    """
    document = await documents_repo.find_by_id(
        session, tenant_id=tenant_id, document_id=document_id
    )
    if document is None:
        raise DocumentNotFoundError(document_id)
    active = await ingestion_jobs_repo.find_active_for_document(session, document_id=document_id)
    if active is not None:
        raise IngestionJobConflictError(active.id)
    job = await ingestion_jobs_repo.create(session, tenant_id=tenant_id, document_id=document_id)
    logger.info("ingestion job queued tenant=%s document=%s job=%s", tenant_id, document_id, job.id)
    await audit_repo.record(
        session,
        tenant_id=tenant_id,
        request_id=current_request_id(),
        action="ingestion.enqueue",
        actor=current_actor(),
        resource_type="ingestion_job",
        resource_id=job.id,
        detail={"document_id": str(document_id)},
    )
    return job


async def get_ingestion_job(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> IngestionJob:
    """Fetch one ingestion job scoped to the tenant.

    Raises IngestionJobNotFoundError for unknown ids and other tenants' rows alike.
    """
    job = await ingestion_jobs_repo.find_by_id(session, tenant_id=tenant_id, job_id=job_id)
    if job is None:
        raise IngestionJobNotFoundError(job_id)
    return job


async def run_next_ingestion_job(
    session: AsyncSession, *, llm: OpenAiClient, data_dir: str
) -> bool:
    """Claim and process one runnable job; True when a job was claimed."""
    job = await ingestion_jobs_repo.claim_next_queued(session)
    if job is None:
        return False
    if job.status is IngestionJobStatus.failed:
        # Claimed past the attempt cap: terminal, nothing to run — but the
        # document must still land in a terminal status, never stuck `uploaded`.
        document = await documents_repo.find_by_id(
            session, tenant_id=job.tenant_id, document_id=job.document_id
        )
        if document is not None:
            await documents_repo.set_status(session, document, DocumentStatus.failed)
        logger.warning("ingestion job capped tenant=%s job=%s", job.tenant_id, job.id)
        return True
    document = await documents_repo.find_by_id(
        session, tenant_id=job.tenant_id, document_id=job.document_id
    )
    if document is None:
        # FK guarantees the row; only a manual delete could race this.
        await ingestion_jobs_repo.mark_failed(
            session, job, error=f"document {job.document_id} vanished after enqueue"
        )
        return True
    try:
        parsed, chunks, embeddings = await _ingest(
            llm,
            data_dir,
            document,
            usage_sink=usage_service.sink(
                session,
                tenant_id=job.tenant_id,
                job_type=UsageJobKind.ingestion,
                job_id=job.id,
            ),
        )
    except Exception as exc:
        logger.warning(
            "ingestion job failed tenant=%s job=%s reason=%s", job.tenant_id, job.id, exc
        )
        await ingestion_jobs_repo.mark_failed(session, job, error=str(exc))
        await documents_repo.set_status(session, document, DocumentStatus.failed)
        return True
    # Text and chunks land in one transaction: a crash between the two writes
    # must never leave new parsed text beside the previous run's chunks.
    await document_texts_repo.replace(
        session,
        tenant_id=job.tenant_id,
        document_id=document.id,
        text=parsed.text,
        page_map=parsed.page_map,
    )
    await document_chunks_repo.replace_with_embeddings(
        session,
        tenant_id=job.tenant_id,
        document_id=document.id,
        chunks=[(chunk.text, chunk.char_start, chunk.char_end) for chunk in chunks],
        embeddings=embeddings,
    )
    await session.commit()
    await ingestion_jobs_repo.mark_completed(session, job, result={"chunk_count": len(chunks)})
    await documents_repo.set_status(session, document, DocumentStatus.parsed)
    logger.info(
        "ingestion job completed tenant=%s job=%s chunks=%d", job.tenant_id, job.id, len(chunks)
    )
    return True


async def _ingest(
    llm: OpenAiClient, data_dir: str, document: Document, *, usage_sink: UsageSink
) -> tuple[ParsedDocument, list, list[list[float]]]:
    """Parse stored bytes, chunk the parsed text, embed the chunk texts."""
    path = local_storage.document_path(data_dir, document.tenant_id, document.sha256)
    content = await asyncio.to_thread(Path.read_bytes, path)
    parsed = await asyncio.to_thread(parse, document.mime_type, content)
    chunks = chunk_document(parsed)
    embeddings = await _embed_chunk_texts(
        llm, [chunk.text for chunk in chunks], usage_sink=usage_sink
    )
    return parsed, chunks, embeddings


async def _embed_chunk_texts(
    llm: OpenAiClient, texts: list[str], *, usage_sink: UsageSink
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH):
        reply = await llm.embed(texts[start : start + _EMBED_BATCH])
        # One row per embed batch: each batch is its own LLM call.
        await usage_sink(reply.usage)
        vectors.extend(reply.vectors)
    return vectors
