"""Generate the landing page's Sample Report from a real pipeline run.

Takes the diff golden record's base/amended texts, uploads them as plain-text
documents under a fixed sample tenant in the dev database, drives ingestion +
extraction + one change report to completion with real LLM calls, and writes
the completed report to web/src/lib/sample-report.json.

ADR-012: the landing showcase is a real report, never a mockup — re-run this
whenever the report payload changes and commit the artifact.

    docker compose up -d --wait
    uv run python -m scripts.make_sample_report

Needs OPENAI_API_KEY. Re-runs reuse the uploaded documents and a completed
extraction; every run makes one fresh change report (a few cents).
"""

import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.repositories.documents as documents_repo
import app.repositories.extraction_jobs as extraction_jobs_repo
from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.llm.client import OpenAiClient
from app.models.change_report_job import ChangeReportJob, ChangeReportJobStatus
from app.models.document import Document, DocumentStatus
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.services.change_report import (
    enqueue_change_report,
    get_change_report_job,
    run_next_change_report_job,
)
from app.services.documents import DocumentAlreadyExistsError, upload_document
from app.services.extraction import enqueue_extraction, get_extraction_job, run_next_extraction_job
from app.services.ingestion import (
    IngestionJobConflictError,
    enqueue_ingestion,
    get_ingestion_job,
    run_next_ingestion_job,
)

GOLDEN_DIFF = Path(__file__).resolve().parent.parent / "evals" / "golden" / "diff.jsonl"
OUTPUT = Path(__file__).resolve().parent.parent / "web" / "src" / "lib" / "sample-report.json"

# Fixed so the report is reproducible and re-runs reuse the same documents.
SAMPLE_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-0000000005a3")

_AGREEMENT_FILENAME = "content-license-agreement.txt"
_AMENDMENT_FILENAME = "content-license-amendment.txt"

# Bounded because the worker handlers claim any queued job in the database,
# not just ours (same caveat as evals/seed_fixtures.py).
_MAX_WORKER_PASSES = 50


def _golden_texts() -> tuple[str, str]:
    record = json.loads(GOLDEN_DIFF.read_text().splitlines()[0])
    return record["input"]["base_text"], record["input"]["amended_text"]


async def _upload(
    session_maker: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    filename: str,
    text: str,
    amends_document_id: uuid.UUID | None = None,
) -> Document:
    content = text.encode()
    consumed = False

    async def read(_size: int) -> bytes:
        nonlocal consumed
        if consumed:
            return b""
        consumed = True
        return content

    async with session_maker() as session:
        try:
            return await upload_document(
                session,
                tenant_id=SAMPLE_TENANT_ID,
                filename=filename,
                content_type="text/plain",
                read=read,
                data_dir=settings.data_dir,
                max_bytes=settings.max_upload_mb * 1024 * 1024,
                amends_document_id=amends_document_id,
            )
        except DocumentAlreadyExistsError:
            existing = await documents_repo.find_by_sha256(
                session, tenant_id=SAMPLE_TENANT_ID, sha256=hashlib.sha256(content).hexdigest()
            )
            if existing is None:
                raise RuntimeError(f"{filename}: dedupe fired but no document row found") from None
            return existing


async def _ensure_ingested(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    settings: Settings,
    document: Document,
) -> None:
    if document.status is DocumentStatus.parsed:
        return
    async with session_maker() as session:
        try:
            job = await enqueue_ingestion(
                session, tenant_id=SAMPLE_TENANT_ID, document_id=document.id
            )
        except IngestionJobConflictError as exc:
            raise RuntimeError(
                f"{document.filename}: active ingestion job {exc.job_id} — rerun in a moment"
            ) from exc
    job = await _drive_ingestion(session_maker, llm, settings.data_dir, job.id)
    if job.status is not IngestionJobStatus.completed:
        raise RuntimeError(f"{document.filename}: ingestion failed: {job.error}")


async def _drive_ingestion(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    data_dir: str,
    job_id: uuid.UUID,
) -> IngestionJob:
    for _ in range(_MAX_WORKER_PASSES):
        async with session_maker() as session:
            job = await get_ingestion_job(session, tenant_id=SAMPLE_TENANT_ID, job_id=job_id)
            if job.status in (IngestionJobStatus.completed, IngestionJobStatus.failed):
                return job
            if not await run_next_ingestion_job(session, llm=llm, data_dir=data_dir):
                break
    raise RuntimeError(f"ingestion job {job_id} never reached a terminal state")


async def _ensure_extracted(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    settings: Settings,
    document: Document,
) -> None:
    async with session_maker() as session:
        latest = await extraction_jobs_repo.find_latest_for_document(
            session, document_id=document.id
        )
        if latest is not None and latest.status is ExtractionJobStatus.completed:
            return
        job = await enqueue_extraction(session, tenant_id=SAMPLE_TENANT_ID, document_id=document.id)
    job = await _drive_extraction(session_maker, llm, settings, job.id)
    if job.status is not ExtractionJobStatus.completed:
        raise RuntimeError(f"{document.filename}: extraction failed: {job.error}")


async def _drive_extraction(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    settings: Settings,
    job_id: uuid.UUID,
) -> ExtractionJob:
    for _ in range(_MAX_WORKER_PASSES):
        async with session_maker() as session:
            job = await get_extraction_job(session, tenant_id=SAMPLE_TENANT_ID, job_id=job_id)
            if job.status in (ExtractionJobStatus.completed, ExtractionJobStatus.failed):
                return job
            if not await run_next_extraction_job(
                session, llm=llm, review_threshold=settings.review_confidence_threshold_extraction
            ):
                break
    raise RuntimeError(f"extraction job {job_id} never reached a terminal state")


async def _generate_report(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    settings: Settings,
    base: Document,
    amendment: Document,
) -> ChangeReportJob:
    async with session_maker() as session:
        job = await enqueue_change_report(
            session,
            tenant_id=SAMPLE_TENANT_ID,
            base_document_id=base.id,
            amended_document_id=amendment.id,
        )
    for _ in range(_MAX_WORKER_PASSES):
        async with session_maker() as session:
            current = await get_change_report_job(
                session, tenant_id=SAMPLE_TENANT_ID, job_id=job.id
            )
            if current.status in (ChangeReportJobStatus.completed, ChangeReportJobStatus.failed):
                return current
            if not await run_next_change_report_job(
                session,
                llm=llm,
                review_threshold=settings.review_confidence_threshold_impact,
            ):
                break
    raise RuntimeError(f"change report job {job.id} never reached a terminal state")


async def main() -> None:
    settings = get_settings()
    base_text, amended_text = _golden_texts()
    llm = OpenAiClient(settings)
    init_engine(settings.database_url)
    session_maker = get_sessionmaker()
    try:
        base = await _upload(session_maker, settings, filename=_AGREEMENT_FILENAME, text=base_text)
        amendment = await _upload(
            session_maker,
            settings,
            filename=_AMENDMENT_FILENAME,
            text=amended_text,
            amends_document_id=base.id,
        )
        await _ensure_ingested(session_maker, llm, settings, base)
        await _ensure_ingested(session_maker, llm, settings, amendment)
        await _ensure_extracted(session_maker, llm, settings, base)
        await _ensure_extracted(session_maker, llm, settings, amendment)
        report = await _generate_report(session_maker, llm, settings, base, amendment)
        if report.status is not ChangeReportJobStatus.completed or report.result is None:
            raise RuntimeError(f"change report failed: {report.error}")
        artifact = {
            "generated_at": report.updated_at.isoformat(),
            "base_filename": base.filename,
            "amended_filename": amendment.filename,
            "changes": report.result["changes"],
        }
        OUTPUT.write_text(json.dumps(artifact, indent=2) + "\n")
        print(f"wrote {OUTPUT} ({len(artifact['changes'])} changes)")
    finally:
        await llm.aclose()
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
