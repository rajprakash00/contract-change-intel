"""Seed the published demo tenant (ADR-011): upload the sample Agreement and
Amendment, then run Ingestion, Extraction and one Change Report so the demo
shows finished output before a visitor spends any budget.

Run: uv run python scripts/seed_demo.py [--tenant-id <uuid>]

Without --tenant-id the first UUID in DEMO_TENANT_IDS is used. Idempotent and
repairing: a completed Change Report means "already seeded" (no-op, no LLM
spend); anything short of it — a partial earlier run — is driven to
completion, reusing rows that already exist. The script drives the real
services directly, like the worker does; it never passes through the API, so
no rate limit is spent. Run it while the worker is idle: a job claimed by a
concurrent worker is waited for, not duplicated.
"""

import argparse
import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

import app.db as db
import app.repositories.change_report_jobs as change_report_jobs_repo
import app.repositories.documents as documents_repo
import app.repositories.extraction_jobs as extraction_jobs_repo
import app.repositories.ingestion_jobs as ingestion_jobs_repo
from app.config import Settings, get_settings
from app.llm.client import OpenAiClient
from app.models.change_report_job import ChangeReportJobStatus
from app.models.document import Document
from app.models.extraction_job import ExtractionJob
from app.models.ingestion_job import IngestionJob
from app.services import change_report, documents, extraction, ingestion

_DEMO_DIR = Path(__file__).parent / "demo_data"
_AGREEMENT_PATH = _DEMO_DIR / "agreement.txt"
_AMENDMENT_PATH = _DEMO_DIR / "amendment.txt"
# Hashed at import: the sample files are part of the repo, and hashing here
# keeps every sha comparison below a plain constant lookup.
_AGREEMENT_SHA256 = hashlib.sha256(_AGREEMENT_PATH.read_bytes()).hexdigest()
_AMENDMENT_SHA256 = hashlib.sha256(_AMENDMENT_PATH.read_bytes()).hexdigest()


def _reader(content: bytes) -> Callable[[int], Awaitable[bytes]]:
    """Serve the whole file on the first read, then EOF — the upload stream
    contract `upload_document` consumes."""
    sent = {"done": False}

    async def read(size: int) -> bytes:
        if sent["done"]:
            return b""
        sent["done"] = True
        return content

    return read


async def _upload(
    settings: Settings,
    tenant_id: uuid.UUID,
    path: Path,
    sha256: str,
    *,
    amends_document_id: uuid.UUID | None = None,
) -> Document:
    """Upload the sample file, reusing an existing row for the same bytes —
    the content-addressed dedupe is what makes re-running the seed safe."""
    content = await asyncio.to_thread(path.read_bytes)
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        try:
            return await documents.upload_document(
                session,
                tenant_id=tenant_id,
                filename=path.name,
                content_type="text/plain",
                read=_reader(content),
                data_dir=settings.data_dir,
                max_bytes=settings.max_upload_mb * 1024 * 1024,
                amends_document_id=amends_document_id,
            )
        except documents.DocumentAlreadyExistsError:
            await session.rollback()
            existing = await documents_repo.find_by_sha256(
                session, tenant_id=tenant_id, sha256=sha256
            )
            if existing is None:
                raise
            return existing


async def _job_status(
    getter: Callable[..., Awaitable], session, tenant_id: uuid.UUID, job_id: uuid.UUID
) -> str:
    job = await getter(session, tenant_id=tenant_id, job_id=job_id)
    return job.status.value


async def _drain_to_completion(
    run_next: Callable[[], Awaitable[bool]], status: Callable[[], Awaitable[str]]
) -> None:
    """Drive until ours reports `completed`; a failed seeded job is an error,
    not a silent success — the demo depends on the finished output.

    The run functions claim any queued job of that kind, so the loop may
    process other tenants' work first — the worker would run it anyway. A
    drained queue without a completed job means the job vanished, not success.
    """
    while True:
        state = await status()
        if state == "completed":
            return
        if state == "failed":
            raise RuntimeError("a seeded job failed; wipe the tenant and re-run the seed")
        if not await run_next():
            raise RuntimeError("job queue drained before the seeded job finished")


async def _enqueue_ingestion(session, tenant_id: uuid.UUID, document_id: uuid.UUID) -> IngestionJob:
    """Enqueue, or adopt the active job when one is already in flight — a
    partially-run earlier seed leaves jobs behind, and re-running must drive
    those to completion rather than duplicate them."""
    try:
        return await ingestion.enqueue_ingestion(
            session, tenant_id=tenant_id, document_id=document_id
        )
    except ingestion.IngestionJobConflictError:
        latest = await ingestion_jobs_repo.find_latest_for_document(
            session, document_id=document_id
        )
        if latest is None:
            raise
        return latest


async def _enqueue_extraction(
    session, tenant_id: uuid.UUID, document_id: uuid.UUID
) -> ExtractionJob:
    try:
        return await extraction.enqueue_extraction(
            session, tenant_id=tenant_id, document_id=document_id
        )
    except extraction.ExtractionJobConflictError:
        latest = await extraction_jobs_repo.find_latest_for_document(
            session, document_id=document_id
        )
        if latest is None:
            raise
        return latest


async def _seed_ingestion(
    settings: Settings, tenant_id: uuid.UUID, document: Document, llm: OpenAiClient
) -> None:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        job = await _enqueue_ingestion(session, tenant_id, document.id)
    async with sessionmaker() as session:
        await _drain_to_completion(
            lambda: ingestion.run_next_ingestion_job(session, llm=llm, data_dir=settings.data_dir),
            lambda: _job_status(ingestion.get_ingestion_job, session, tenant_id, job.id),
        )


async def _seed_extraction(
    settings: Settings, tenant_id: uuid.UUID, document: Document, llm: OpenAiClient
) -> None:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        job = await _enqueue_extraction(session, tenant_id, document.id)
    async with sessionmaker() as session:
        await _drain_to_completion(
            lambda: extraction.run_next_extraction_job(
                session, llm=llm, review_threshold=settings.review_confidence_threshold_extraction
            ),
            lambda: _job_status(extraction.get_extraction_job, session, tenant_id, job.id),
        )


async def _seed_change_report(
    settings: Settings, tenant_id: uuid.UUID, base: Document, amended: Document, llm: OpenAiClient
) -> None:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        job = await change_report.enqueue_change_report(
            session,
            tenant_id=tenant_id,
            base_document_id=base.id,
            amended_document_id=amended.id,
        )
    async with sessionmaker() as session:
        await _drain_to_completion(
            lambda: change_report.run_next_change_report_job(
                session, llm=llm, review_threshold=settings.review_confidence_threshold_impact
            ),
            lambda: _job_status(change_report.get_change_report_job, session, tenant_id, job.id),
        )


async def seed(tenant_id: uuid.UUID, settings: Settings, llm: OpenAiClient) -> dict[str, object]:
    """Fill one demo tenant; returns a JSON-able summary of what landed.

    A completed Change Report for the seeded pair is the "already seeded"
    state — the no-op, zero-LLM-spend exit. Anything short of it is repaired.
    """
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        agreement = await documents_repo.find_by_sha256(
            session, tenant_id=tenant_id, sha256=_AGREEMENT_SHA256
        )
        amendment = await documents_repo.find_by_sha256(
            session, tenant_id=tenant_id, sha256=_AMENDMENT_SHA256
        )

    if agreement is None:
        if amendment is not None:
            raise RuntimeError(
                "sample amendment exists without the agreement; wipe the tenant and re-run"
            )
        agreement = await _upload(settings, tenant_id, _AGREEMENT_PATH, _AGREEMENT_SHA256)
        amendment = await _upload(
            settings, tenant_id, _AMENDMENT_PATH, _AMENDMENT_SHA256, amends_document_id=agreement.id
        )
    elif amendment is None:
        amendment = await _upload(
            settings, tenant_id, _AMENDMENT_PATH, _AMENDMENT_SHA256, amends_document_id=agreement.id
        )
    else:
        if amendment.amends_document_id != agreement.id:
            raise RuntimeError("sample files exist unlinked; wipe the tenant and re-run")
        async with sessionmaker() as session:
            reports = await change_report_jobs_repo.list_for_base_document(
                session, tenant_id=tenant_id, base_document_id=agreement.id
            )
        if any(report.status is ChangeReportJobStatus.completed for report in reports):
            return {"status": "already_seeded", "documents": 2}

    for document in (agreement, amendment):
        await _seed_ingestion(settings, tenant_id, document, llm)
        await _seed_extraction(settings, tenant_id, document, llm)
    await _seed_change_report(settings, tenant_id, agreement, amendment, llm)

    return {
        "status": "seeded",
        "agreement_id": str(agreement.id),
        "amendment_id": str(amendment.id),
    }


async def _main(tenant_id: uuid.UUID) -> dict[str, object]:
    settings = get_settings()
    db.init_engine(settings.database_url)
    llm = OpenAiClient(settings)  # raises LlmNotConfiguredError when the key is missing
    try:
        return await seed(tenant_id, settings, llm)
    finally:
        await llm.aclose()
        await db.dispose_engine()


def _demo_tenant_id(explicit: str | None) -> uuid.UUID:
    if explicit:
        return uuid.UUID(explicit)
    first = next(
        (
            part.strip().lower()
            for part in get_settings().demo_tenant_ids.split(",")
            if part.strip()
        ),
        None,
    )
    if first is None:
        raise SystemExit("no tenant given and DEMO_TENANT_IDS is empty")
    return uuid.UUID(first)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant-id",
        help="demo tenant UUID; defaults to the first entry of DEMO_TENANT_IDS",
    )
    args = parser.parse_args()
    summary = asyncio.run(_main(_demo_tenant_id(args.tenant_id)))
    print(json.dumps(summary, indent=2))
