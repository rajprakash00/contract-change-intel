import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction_job import ExtractionJob, ExtractionJobStatus


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


async def claim_next_queued(session: AsyncSession) -> ExtractionJob | None:
    """Atomically claim the oldest queued job: row-locked, committed as running.

    FOR UPDATE SKIP LOCKED makes concurrent workers safe: each claims a
    different row or gets None. A worker crash mid-run leaves the row `running`
    (stuck until manual requeue); recovery for that gap is deferred until the
    W3 ingestion pipeline defines retry policy.
    """
    result = await session.execute(
        select(ExtractionJob)
        .where(ExtractionJob.status == ExtractionJobStatus.queued)
        .order_by(ExtractionJob.created_at.asc(), ExtractionJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.status = ExtractionJobStatus.running
    await session.commit()
    await session.refresh(job)
    return job


async def mark_completed(
    session: AsyncSession, job: ExtractionJob, *, result: dict
) -> ExtractionJob:
    job.status = ExtractionJobStatus.completed
    job.result = result
    job.error = None
    await session.commit()
    await session.refresh(job)
    return job


async def mark_failed(session: AsyncSession, job: ExtractionJob, *, error: str) -> ExtractionJob:
    job.status = ExtractionJobStatus.failed
    job.result = None
    job.error = error[:1024]
    await session.commit()
    await session.refresh(job)
    return job
