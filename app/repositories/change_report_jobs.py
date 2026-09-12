import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change_report_job import ChangeReportJob, ChangeReportJobStatus
from app.repositories import job_claims


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    base_document_id: uuid.UUID,
    amended_document_id: uuid.UUID,
) -> ChangeReportJob:
    job = ChangeReportJob(
        tenant_id=tenant_id,
        base_document_id=base_document_id,
        amended_document_id=amended_document_id,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def find_by_id(
    session: AsyncSession, *, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> ChangeReportJob | None:
    result = await session.execute(
        select(ChangeReportJob).where(
            ChangeReportJob.id == job_id, ChangeReportJob.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()


async def claim_next_queued(session: AsyncSession) -> ChangeReportJob | None:
    """Atomically claim the oldest runnable job (lease-at-claim, ADR-004 amendment)."""
    return await job_claims.claim_next(
        session,
        ChangeReportJob,
        queued=ChangeReportJobStatus.queued,
        running=ChangeReportJobStatus.running,
        failed=ChangeReportJobStatus.failed,
    )


async def mark_completed(
    session: AsyncSession, job: ChangeReportJob, *, result: dict
) -> ChangeReportJob:
    job.status = ChangeReportJobStatus.completed
    job.result = result
    job.error = None
    job.lease_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job


async def mark_failed(
    session: AsyncSession, job: ChangeReportJob, *, error: str
) -> ChangeReportJob:
    job.status = ChangeReportJobStatus.failed
    job.result = None
    job.error = error[:1024]
    job.lease_expires_at = None
    await session.commit()
    await session.refresh(job)
    return job


async def delete_for_amendment(
    session: AsyncSession, *, amended_document_id: uuid.UUID
) -> list[uuid.UUID]:
    """Delete the Change Reports naming this document as the Amendment and
    return their ids, so callers can delete the Review Items routed from
    them. A report whose base is the deleted document cannot exist here:
    a base with amendments is refused upstream (409). No commit: the
    document-delete sweep commits once at the end."""
    ids = list(
        (
            await session.execute(
                select(ChangeReportJob.id).where(
                    ChangeReportJob.amended_document_id == amended_document_id
                )
            )
        ).scalars()
    )
    if ids:
        await session.execute(delete(ChangeReportJob).where(ChangeReportJob.id.in_(ids)))
    return ids
