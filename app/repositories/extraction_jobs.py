import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.repositories import job_claims


async def create(
    session: AsyncSession, *, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> ExtractionJob:
    job = ExtractionJob(tenant_id=tenant_id, document_id=document_id)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def find_by_id(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> ExtractionJob | None:
    result = await session.execute(
        select(ExtractionJob).where(
            ExtractionJob.id == job_id, ExtractionJob.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()


async def find_active_for_document(
    session: AsyncSession, *, document_id: uuid.UUID
) -> ExtractionJob | None:
    """The unfinished job for a document, if any — gates the 409 re-run rule."""
    result = await session.execute(
        select(ExtractionJob)
        .where(
            ExtractionJob.document_id == document_id,
            ExtractionJob.status.in_([ExtractionJobStatus.queued, ExtractionJobStatus.running]),
        )
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_latest_for_document(
    session: AsyncSession, *, document_id: uuid.UUID
) -> ExtractionJob | None:
    """The most recent job for a document, any status.

    Names the prerequisite that is not completed when a downstream surface
    (change reports) rejects a document without a completed extraction.
    """
    result = await session.execute(
        select(ExtractionJob)
        .where(ExtractionJob.document_id == document_id)
        .order_by(ExtractionJob.created_at.desc(), ExtractionJob.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def claim_next_queued(session: AsyncSession) -> ExtractionJob | None:
    """Atomically claim the oldest runnable job (lease-at-claim, ADR-004 amendment).

    FOR UPDATE SKIP LOCKED makes concurrent workers safe: each claims a
    different row or gets None. A worker crash mid-run leaves the row
    `running` until its lease lapses, when another worker may claim it again.
    """
    return await job_claims.claim_next(
        session,
        ExtractionJob,
        queued=ExtractionJobStatus.queued,
        running=ExtractionJobStatus.running,
        failed=ExtractionJobStatus.failed,
    )


async def mark_completed(
    session: AsyncSession, job: ExtractionJob, *, result: dict
) -> ExtractionJob:
    job.status = ExtractionJobStatus.completed
    job.result = result
    job.error = None
    job.lease_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job


async def mark_failed(session: AsyncSession, job: ExtractionJob, *, error: str) -> ExtractionJob:
    job.status = ExtractionJobStatus.failed
    job.result = None
    job.error = error[:1024]
    job.lease_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job
