import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.repositories import job_claims


async def create(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> IngestionJob:
    job = IngestionJob(tenant_id=tenant_id, document_id=document_id)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def find_by_id(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> IngestionJob | None:
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.id == job_id, IngestionJob.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def find_active_for_document(
    session: AsyncSession, *, document_id: uuid.UUID
) -> IngestionJob | None:
    """The unfinished job for a document, if any — gates the 409 re-run rule."""
    result = await session.execute(
        select(IngestionJob)
        .where(
            IngestionJob.document_id == document_id,
            IngestionJob.status.in_([IngestionJobStatus.queued, IngestionJobStatus.running]),
        )
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_for_document(
    session: AsyncSession, *, document_id: uuid.UUID
) -> IngestionJob | None:
    """The most recent job for a document, any status.

    Names the prerequisite that is not completed when a downstream surface
    (extraction) rejects an unparsed document with 409.
    """
    result = await session.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document_id)
        .order_by(IngestionJob.created_at.desc(), IngestionJob.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def claim_next_queued(session: AsyncSession) -> IngestionJob | None:
    """Atomically claim the oldest runnable job (lease-at-claim, ADR-004 amendment)."""
    return await job_claims.claim_next(
        session,
        IngestionJob,
        queued=IngestionJobStatus.queued,
        running=IngestionJobStatus.running,
        failed=IngestionJobStatus.failed,
    )


async def mark_completed(session: AsyncSession, job: IngestionJob, *, result: dict) -> IngestionJob:
    job.status = IngestionJobStatus.completed
    job.result = result
    job.error = None
    job.lease_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job


async def mark_failed(session: AsyncSession, job: IngestionJob, *, error: str) -> IngestionJob:
    job.status = IngestionJobStatus.failed
    job.result = None
    job.error = error[:1024]
    job.lease_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job


async def delete_for_document(session: AsyncSession, *, document_id: uuid.UUID) -> None:
    """Delete a document's ingestion jobs. No commit: the document-delete
    sweep commits once at the end."""
    await session.execute(delete(IngestionJob).where(IngestionJob.document_id == document_id))
