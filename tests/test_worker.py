"""Integration tests for the worker's round-robin scheduling across both job
tables (real Postgres; LLM/embedding wires faked at the httpx2 seam).
"""

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
import app.repositories.document_texts as texts_repo
import app.repositories.documents as documents_repo
import app.repositories.extraction_jobs as extraction_jobs_repo
import app.repositories.ingestion_jobs as ingestion_jobs_repo
from app.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.document_text import DocumentText
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.services.extraction import enqueue_extraction
from app.services.ingestion import enqueue_ingestion
from app.storage import local
from app.worker import run_next_job
from tests.fake_openai import fake_embedding_client, fake_llm_client

VALID_OUTPUT = json.dumps(
    {
        "obligations": [
            {
                "clause_ref": "8.2",
                "description": "Supplier shall deliver monthly status reports",
                "owner": "Supplier",
                "citation": {"char_start": 0, "char_end": 9},
                "confidence": 0.9,
            }
        ],
        "defined_terms": [],
    }
)

FAKE_VECTOR = [0.001 * (i % 10) for i in range(EMBEDDING_DIMENSIONS)]


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    async with db.get_sessionmaker()() as s:
        yield s


@pytest.fixture(autouse=True)
async def engine() -> AsyncIterator[None]:
    db.init_engine(get_settings().database_url)
    yield
    await db.dispose_engine()


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with session() as s:
        await s.execute(delete(DocumentChunk))
        await s.execute(delete(DocumentText))
        await s.execute(delete(ExtractionJob))
        await s.execute(delete(IngestionJob))
        await s.execute(delete(Document))
        await s.commit()


async def make_text_document(data_dir: Path) -> Document:
    tenant_id = uuid.uuid4()
    async with session() as s:
        document = await documents_repo.create(
            s,
            tenant_id=tenant_id,
            filename="msa.txt",
            mime_type="text/plain",
            sha256=uuid.uuid4().hex * 2,
        )
        await texts_repo.replace(
            s,
            tenant_id=tenant_id,
            document_id=document.id,
            text="agreement text",
            page_map=[],
        )
        await documents_repo.set_status(s, document, DocumentStatus.parsed)
    local.save_document(str(data_dir), tenant_id, document.sha256, b"agreement text")
    return document


async def enqueue_one_extraction(document: Document) -> ExtractionJob:
    async with session() as s:
        return await enqueue_extraction(s, tenant_id=document.tenant_id, document_id=document.id)


async def enqueue_one_ingestion(document: Document) -> IngestionJob:
    async with session() as s:
        return await enqueue_ingestion(s, tenant_id=document.tenant_id, document_id=document.id)


async def test_round_robin_serves_both_queues_regardless_of_start(data_dir: Path) -> None:
    document = await make_text_document(data_dir)
    extraction_job = await enqueue_one_extraction(document)
    ingestion_job = await enqueue_one_ingestion(document)

    async with (
        fake_llm_client(VALID_OUTPUT) as (llm, _),
        fake_embedding_client([FAKE_VECTOR]) as (embed_llm, _),
    ):
        async with session() as s:
            ran_first = await run_next_job(s, llm=llm, data_dir=str(data_dir), first=0)
        async with session() as s:
            ran_second = await run_next_job(s, llm=embed_llm, data_dir=str(data_dir), first=1)

    assert ran_first is True
    assert ran_second is True
    async with session() as s:
        extraction_done = await extraction_jobs_repo.find_by_id(
            s, tenant_id=document.tenant_id, job_id=extraction_job.id
        )
        ingestion_done = await ingestion_jobs_repo.find_by_id(
            s, tenant_id=document.tenant_id, job_id=ingestion_job.id
        )
    assert extraction_done is not None
    assert extraction_done.status is ExtractionJobStatus.completed
    assert ingestion_done is not None
    assert ingestion_done.status is IngestionJobStatus.completed


async def test_one_pass_runs_at_most_one_job_per_queue(data_dir: Path) -> None:
    # An extraction backlog must not starve ingestion: with first=0, one pass
    # completes exactly one extraction and then moves on, leaving the other
    # extraction and the ingestion job untouched.
    document = await make_text_document(data_dir)
    other_document = await make_text_document(data_dir)
    await enqueue_one_extraction(document)
    await enqueue_one_extraction(other_document)
    ingestion_job = await enqueue_one_ingestion(document)

    async with fake_llm_client(VALID_OUTPUT) as (llm, _), session() as s:
        ran = await run_next_job(s, llm=llm, data_dir=str(data_dir), first=0)

    assert ran is True
    async with session() as s:
        jobs = (await s.execute(select(ExtractionJob))).scalars().all()
        untouched_ingestion = await ingestion_jobs_repo.find_by_id(
            s, tenant_id=document.tenant_id, job_id=ingestion_job.id
        )
    completed = [job for job in jobs if job.status is ExtractionJobStatus.completed]
    queued = [job for job in jobs if job.status is ExtractionJobStatus.queued]
    assert len(completed) == 1
    assert len(queued) == 1
    assert untouched_ingestion is not None
    assert untouched_ingestion.status is IngestionJobStatus.queued


async def test_idle_queues_report_no_work() -> None:
    async with fake_llm_client(VALID_OUTPUT) as (llm, _), session() as s:
        ran = await run_next_job(s, llm=llm, data_dir="/nonexistent", first=0)

    assert ran is False
