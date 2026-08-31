"""Integration tests for the ADR-004 amendment: lease-at-claim retry.

Locked symmetrically over both job tables through their repositories — the
same claim semantics must hold for extraction and ingestion alike. A crashed
worker is simulated by writing a stale `running` row with an expired lease.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app.config import get_settings
from app.models.document import Document
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.repositories import extraction_jobs, ingestion_jobs
from app.repositories.job_claims import LEASE_SECONDS, MAX_ATTEMPTS

CASES = [
    pytest.param(ExtractionJob, ExtractionJobStatus, extraction_jobs, id="extraction"),
    pytest.param(IngestionJob, IngestionJobStatus, ingestion_jobs, id="ingestion"),
]


@pytest.fixture(autouse=True)
async def engine() -> AsyncIterator[None]:
    db.init_engine(get_settings().database_url)
    yield
    await db.dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with db.get_sessionmaker()() as s:
        await s.execute(delete(ExtractionJob))
        await s.execute(delete(IngestionJob))
        await s.execute(delete(Document))
        await s.commit()


async def make_document(s: AsyncSession) -> Document:
    document = Document(
        tenant_id=uuid.uuid4(),
        filename="msa.txt",
        mime_type="text/plain",
        sha256=uuid.uuid4().hex * 2,
    )
    s.add(document)
    await s.commit()
    await s.refresh(document)
    return document


async def force_state(job, *, status, lease_expires_at=None, attempts=None) -> None:
    """Write job state directly, simulating whatever a crashed worker left behind."""
    async with db.get_sessionmaker()() as s:
        stored = await s.get(type(job), job.id)
        assert stored is not None
        stored.status = status
        stored.lease_expires_at = lease_expires_at
        if attempts is not None:
            stored.attempts = attempts
        await s.commit()


@pytest.mark.parametrize(("model", "status_enum", "repo"), CASES)
class TestClaimNext:
    async def test_queued_job_claims_to_running_with_lease_and_attempt(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)

        async with db.get_sessionmaker()() as s:
            claimed = await repo.claim_next_queued(s)

        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status is status_enum.running
        assert claimed.attempts == 1
        assert claimed.lease_expires_at is not None
        remaining = claimed.lease_expires_at - datetime.now(UTC)
        assert remaining <= timedelta(seconds=LEASE_SECONDS)
        assert remaining > timedelta(seconds=LEASE_SECONDS - 60)

    async def test_running_job_with_expired_lease_is_reclaimed(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
        await force_state(
            job,
            status=status_enum.running,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            attempts=1,
        )

        async with db.get_sessionmaker()() as s:
            claimed = await repo.claim_next_queued(s)

        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.attempts == 2
        assert claimed.lease_expires_at is not None
        assert claimed.lease_expires_at > datetime.now(UTC)

    async def test_running_job_inside_its_lease_is_not_claimable(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
        await force_state(
            job,
            status=status_enum.running,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            attempts=1,
        )

        async with db.get_sessionmaker()() as s:
            claimed = await repo.claim_next_queued(s)

        assert claimed is None, "a leased row must not be double-claimed"
        async with db.get_sessionmaker()() as s:
            stored = await s.get(model, job.id)
        assert stored is not None
        assert stored.status is status_enum.running
        assert stored.attempts == 1

    async def test_claim_past_attempt_cap_lands_in_failed_max_attempts_exceeded(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
        await force_state(
            job,
            status=status_enum.running,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            attempts=MAX_ATTEMPTS,
        )

        async with db.get_sessionmaker()() as s:
            claimed = await repo.claim_next_queued(s)

        assert claimed is not None, "a capped job is claimed into failed and surfaced"
        assert claimed.id == job.id
        assert claimed.status is status_enum.failed
        assert claimed.error == "max_attempts_exceeded"
        assert claimed.attempts == MAX_ATTEMPTS + 1
        assert claimed.lease_expires_at is None

    async def test_oldest_job_claims_first(self, model, status_enum, repo) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            newer = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
            older = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
            await s.execute(
                model.__table__.update()
                .where(model.id == older.id)
                .values(created_at=datetime.now(UTC) - timedelta(minutes=1))
            )
            await s.commit()

        async with db.get_sessionmaker()() as s:
            claimed = await repo.claim_next_queued(s)

        assert claimed is not None
        assert claimed.id == older.id
        assert claimed.id != newer.id

    async def test_terminal_jobs_are_never_claimed(self, model, status_enum, repo) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            for terminal in (status_enum.completed, status_enum.failed):
                job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
                stored = await s.get(model, job.id)
                assert stored is not None
                stored.status = terminal
                await s.commit()

        async with db.get_sessionmaker()() as s:
            claimed = await repo.claim_next_queued(s)

        assert claimed is None


@pytest.mark.parametrize(("model", "status_enum", "repo"), CASES)
class TestMarkTerminal:
    async def test_mark_completed_sets_result_and_clears_lease(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
        await force_state(
            job,
            status=status_enum.running,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            attempts=1,
        )

        async with db.get_sessionmaker()() as s:
            stored = await s.get(model, job.id)
            assert stored is not None
            done = await repo.mark_completed(s, stored, result={"chunk_count": 2})

        assert done.status is status_enum.completed
        assert done.result == {"chunk_count": 2}
        assert done.error is None
        assert done.lease_expires_at is None, "a completed row must never look leased"

    async def test_mark_failed_sets_error_and_clears_lease(self, model, status_enum, repo) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            job = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)
        await force_state(
            job,
            status=status_enum.running,
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=10),
            attempts=1,
        )

        async with db.get_sessionmaker()() as s:
            stored = await s.get(model, job.id)
            assert stored is not None
            failed = await repo.mark_failed(s, stored, error="parser exploded" * 200)

        assert failed.status is status_enum.failed
        assert failed.result is None
        assert failed.lease_expires_at is None
        assert len(failed.error or "") <= 1024

    async def test_find_active_for_document_sees_only_unfinished_work(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            document = await make_document(s)
            first = await repo.create(s, tenant_id=document.tenant_id, document_id=document.id)

        async with db.get_sessionmaker()() as s:
            active = await repo.find_active_for_document(s, document_id=document.id)

        assert active is not None
        assert active.id == first.id
        await force_state(first, status=status_enum.completed)

        async with db.get_sessionmaker()() as s:
            active_after_terminal = await repo.find_active_for_document(s, document_id=document.id)

        assert active_after_terminal is None, "terminal jobs must not block a re-run"

    async def test_find_active_for_document_is_empty_without_jobs(
        self, model, status_enum, repo
    ) -> None:
        async with db.get_sessionmaker()() as s:
            active = await repo.find_active_for_document(s, document_id=uuid.uuid4())
        assert active is None
