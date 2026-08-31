"""Shared claim/lease mechanics for the Postgres job tables (ADR-004 amendment).

Both job tables have identical claim semantics, so the SQL lives here once:
oldest eligible row, `FOR UPDATE SKIP LOCKED` for concurrent workers, and
lease-at-claim retry — a row is eligible while `queued` or while `running`
with an expired lease (what a crashed worker leaves behind). Lease duration
and attempt cap are constants, not settings knobs, per the ADR.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

LEASE_SECONDS = 15 * 60
MAX_ATTEMPTS = 3


class JobRow(Protocol):
    """The columns every job table shares (ADR-004 amendment); structural, so
    the claim code stays one definition across both tables. Typed loosely:
    on the class these are SQLAlchemy columns, on instances ORM values."""

    id: Any
    status: Any
    result: Any
    error: Any
    attempts: Any
    lease_expires_at: Any
    created_at: Any


async def claim_next[JobT: JobRow](
    session: AsyncSession,
    model: type[JobT],
    *,
    queued: Any,
    running: Any,
    failed: Any,
) -> JobT | None:
    """Atomically claim the oldest runnable job row; None when nothing is runnable.

    Claiming sets a fresh lease and increments `attempts`. A row past the
    attempt cap claims straight into `failed` with reason
    `max_attempts_exceeded` and is returned in that terminal state — the
    caller must not run it, but gets the chance to do per-domain terminal
    bookkeeping (e.g. flipping the document's status).
    """
    now = datetime.now(UTC)
    result = await session.execute(
        select(model)
        .where(
            or_(
                model.status == queued,
                and_(model.status == running, model.lease_expires_at <= now),
            )
        )
        .order_by(model.created_at.asc(), model.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = result.scalar_one_or_none()
    if job is None:
        return None
    job.attempts += 1
    if job.attempts > MAX_ATTEMPTS:
        job.status = failed
        job.result = None
        job.error = "max_attempts_exceeded"
        job.lease_expires_at = None
    else:
        job.status = running
        job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    await session.commit()
    await session.refresh(job)
    return job
