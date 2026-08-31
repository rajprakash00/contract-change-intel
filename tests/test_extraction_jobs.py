"""Integration tests for the extraction job lifecycle: enqueue, claim, run.

Real Postgres (job + document rows); the LLM wire is faked at the httpx2
transport seam via tests/fake_openai, per the AGENTS.md exception for LLM tests.
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
from app.config import get_settings
from app.llm.client import LlmCallError
from app.models.document import Document
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.repositories import documents as documents_repo
from app.repositories import extraction_jobs as jobs_repo
from app.services.documents import DocumentNotFoundError
from app.services.extraction import (
    ExtractionJobConflictError,
    ExtractionJobNotFoundError,
    enqueue_extraction,
    get_extraction_job,
    run_next_extraction_job,
)
from app.storage import local
from tests.fake_openai import fake_llm_client

VALID_OUTPUT = json.dumps(
    {
        "obligations": [
            {
                "clause_ref": "8.2",
                "description": "Supplier shall deliver monthly status reports",
                "owner": "Supplier",
            }
        ]
    }
)


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """One managed session per call, closed on exit."""
    async with db.get_sessionmaker()() as s:
        yield s


@pytest.fixture(autouse=True)
async def engine() -> AsyncIterator[None]:
    # No HTTP client in these tests, so the engine is initialised here exactly
    # as the app lifespan (and the conftest `client` fixture) would.
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
        await s.execute(delete(ExtractionJob))
        await s.execute(delete(Document))
        await s.commit()


async def make_document(tenant_id: uuid.UUID, *, mime_type: str = "text/plain") -> Document:
    async with session() as s:
        return await documents_repo.create(
            s,
            tenant_id=tenant_id,
            filename="msa.txt",
            mime_type=mime_type,
            sha256=uuid.uuid4().hex * 2,
        )


class TestEnqueueExtraction:
    async def test_enqueue_creates_queued_job_for_existing_document(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)

        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert job.status is ExtractionJobStatus.queued
        assert job.tenant_id == tenant_id
        assert job.document_id == document.id
        assert job.result is None
        assert job.error is None

    async def test_enqueue_unknown_document_raises_document_not_found(self) -> None:
        with pytest.raises(DocumentNotFoundError):
            async with session() as s:
                await enqueue_extraction(s, tenant_id=uuid.uuid4(), document_id=uuid.uuid4())

    async def test_enqueue_while_a_job_is_active_conflicts_with_existing_job_id(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        async with session() as s:
            first = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        with pytest.raises(ExtractionJobConflictError) as excinfo:
            async with session() as s:
                await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert excinfo.value.job_id == first.id

    async def test_enqueue_after_a_terminal_job_starts_a_new_run(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        async with session() as s:
            await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)
        async with session() as s:
            row = (await s.execute(select(ExtractionJob))).scalar_one()
            row.status = ExtractionJobStatus.completed
            await s.commit()

        async with session() as s:
            second = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert second.status is ExtractionJobStatus.queued


class TestGetExtractionJob:
    async def test_get_returns_job_scoped_to_tenant(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with session() as s:
            found = await get_extraction_job(s, tenant_id=tenant_id, job_id=job.id)

        assert found.id == job.id

    async def test_other_tenant_or_unknown_job_reads_as_not_found(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        with pytest.raises(ExtractionJobNotFoundError):
            async with session() as s:
                await get_extraction_job(s, tenant_id=uuid.uuid4(), job_id=job.id)
        with pytest.raises(ExtractionJobNotFoundError):
            async with session() as s:
                await get_extraction_job(s, tenant_id=tenant_id, job_id=uuid.uuid4())


class TestRunNextExtractionJob:
    async def test_no_queued_job_returns_false(self) -> None:
        async with fake_llm_client(VALID_OUTPUT) as (llm, _), session() as s:
            ran = await run_next_extraction_job(s, llm=llm, data_dir="/nonexistent")

        assert ran is False

    async def test_text_document_completes_with_parsed_result(self, tmp_path: Path) -> None:
        tenant_id = uuid.uuid4()
        content = b"Section 8.2: Supplier shall deliver monthly status reports."
        document = await make_document(tenant_id)
        local.save_document(str(tmp_path), tenant_id, document.sha256, content)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with (
            fake_llm_client(VALID_OUTPUT, prompt_tokens=50, completion_tokens=10) as (
                llm,
                requests,
            ),
            session() as s,
        ):
            ran = await run_next_extraction_job(s, llm=llm, data_dir=str(tmp_path))

        assert ran is True
        async with session() as s:
            completed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert completed is not None
        assert completed.status is ExtractionJobStatus.completed
        assert completed.error is None
        assert completed.result == {
            "obligations": [
                {
                    "clause_ref": "8.2",
                    "description": "Supplier shall deliver monthly status reports",
                    "owner": "Supplier",
                }
            ]
        }
        # Document text travelled to the LLM as user data, never as system text.
        sent = json.loads(requests[0].content)
        assert "Section 8.2" in sent["messages"][1]["content"]

    async def test_pdf_document_fails_without_touching_the_llm(self, tmp_path: Path) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id, mime_type="application/pdf")
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with fake_llm_client(VALID_OUTPUT) as (llm, requests), session() as s:
            ran = await run_next_extraction_job(s, llm=llm, data_dir=str(tmp_path))

        assert ran is True
        assert requests == [], "no LLM call may happen for mime types the pipeline can't parse"
        async with session() as s:
            failed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert failed is not None
        assert failed.status is ExtractionJobStatus.failed
        assert failed.result is None
        assert "text/plain" in failed.error
        assert "pdf" in failed.error

    async def test_llm_output_failure_marks_job_failed_not_completed(self, tmp_path: Path) -> None:
        tenant_id = uuid.uuid4()
        content = b"agreement text"
        document = await make_document(tenant_id)
        local.save_document(str(tmp_path), tenant_id, document.sha256, content)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with fake_llm_client("I cannot help with that.") as (llm, _), session() as s:
            ran = await run_next_extraction_job(s, llm=llm, data_dir=str(tmp_path))

        assert ran is True, "the handler must swallow LlmError so the worker loop keeps going"
        async with session() as s:
            failed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert failed is not None
        assert failed.status is ExtractionJobStatus.failed
        assert failed.result is None
        assert "schema validation" in failed.error

    async def test_llm_call_failure_marks_job_failed(self, tmp_path: Path) -> None:
        class FailingLlm:
            async def complete_structured(self, schema, *, system, user):
                raise LlmCallError("gpt-4o-mini", RuntimeError("boom"))

        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        local.save_document(str(tmp_path), tenant_id, document.sha256, b"agreement text")
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with session() as s:
            ran = await run_next_extraction_job(
                s,
                llm=FailingLlm(),
                data_dir=str(tmp_path),  # type: ignore[arg-type]
            )

        assert ran is True
        async with session() as s:
            failed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert failed is not None
        assert failed.status is ExtractionJobStatus.failed
        assert "llm call failed" in failed.error
