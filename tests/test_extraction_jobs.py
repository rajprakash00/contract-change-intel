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
from app.models.document import Document, DocumentStatus
from app.models.document_text import DocumentText
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.models.review_item import ReviewItem, ReviewItemSource, ReviewItemStatus
from app.repositories import document_texts as texts_repo
from app.repositories import documents as documents_repo
from app.repositories import extraction_jobs as jobs_repo
from app.repositories import ingestion_jobs as ingestion_jobs_repo
from app.services.documents import DocumentNotFoundError
from app.services.extraction import (
    DocumentNotParsedError,
    ExtractionJobConflictError,
    ExtractionJobNotFoundError,
    enqueue_extraction,
    get_extraction_job,
    run_next_extraction_job,
)
from app.storage import local
from tests.fake_openai import fake_llm_client, fake_llm_client_queue

PARSED_TEXT = "PARSED 8.2 Supplier shall deliver monthly status reports."


def extraction_output(char_start: int, char_end: int, confidence: float = 0.9) -> str:
    return json.dumps(
        {
            "obligations": [
                {
                    "clause_ref": "8.2",
                    "description": "Supplier shall deliver monthly status reports",
                    "owner": "Supplier",
                    "citation": {"char_start": char_start, "char_end": char_end},
                    "confidence": confidence,
                }
            ],
            "defined_terms": [
                {
                    "term": "Reports",
                    "definition": "the monthly status reports",
                    "citation": {"char_start": char_start, "char_end": char_end},
                    "confidence": 0.7,
                }
            ],
        }
    )


def expected_result(char_start: int, char_end: int) -> dict:
    return {
        "obligations": [
            {
                "clause_ref": "8.2",
                "description": "Supplier shall deliver monthly status reports",
                "owner": "Supplier",
                "citation": {"char_start": char_start, "char_end": char_end},
                "confidence": 0.9,
            }
        ],
        "defined_terms": [
            {
                "term": "Reports",
                "definition": "the monthly status reports",
                "citation": {"char_start": char_start, "char_end": char_end},
                "confidence": 0.7,
            }
        ],
    }


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
        await s.execute(delete(ReviewItem))
        await s.execute(delete(ExtractionJob))
        await s.execute(delete(IngestionJob))
        await s.execute(delete(DocumentText))
        await s.execute(delete(Document))
        await s.commit()


async def make_document(
    tenant_id: uuid.UUID,
    *,
    mime_type: str = "text/plain",
    status: DocumentStatus = DocumentStatus.parsed,
) -> Document:
    async with session() as s:
        document = await documents_repo.create(
            s,
            tenant_id=tenant_id,
            filename="msa.txt",
            mime_type=mime_type,
            sha256=uuid.uuid4().hex * 2,
        )
        if status is not DocumentStatus.uploaded:
            await documents_repo.set_status(s, document, status)
        return document


async def make_ingestion_job(document: Document, status: IngestionJobStatus) -> IngestionJob:
    async with session() as s:
        job = await ingestion_jobs_repo.create(
            s, tenant_id=document.tenant_id, document_id=document.id
        )
        stored = await s.get(IngestionJob, job.id)
        assert stored is not None
        stored.status = status
        await s.commit()
        return stored


async def seed_parsed_text(tenant_id: uuid.UUID, document_id: uuid.UUID, text: str) -> None:
    async with session() as s:
        await texts_repo.replace(
            s, tenant_id=tenant_id, document_id=document_id, text=text, page_map=[]
        )
        await s.commit()


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


class TestEnqueueGatingOnIngestion:
    """Extraction requires a parsed document: uploaded/failed documents are
    rejected with 409 naming the ingestion job that is not completed."""

    async def test_never_ingested_document_is_rejected_without_an_ingestion_job(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id, status=DocumentStatus.uploaded)

        with pytest.raises(DocumentNotParsedError) as excinfo:
            async with session() as s:
                await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert excinfo.value.ingestion_job_id is None

    async def test_document_with_running_ingestion_is_rejected_naming_that_job(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id, status=DocumentStatus.uploaded)
        ingestion = await make_ingestion_job(document, IngestionJobStatus.running)

        with pytest.raises(DocumentNotParsedError) as excinfo:
            async with session() as s:
                await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert excinfo.value.ingestion_job_id == ingestion.id

    async def test_document_with_failed_ingestion_is_rejected_naming_that_job(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id, status=DocumentStatus.failed)
        ingestion = await make_ingestion_job(document, IngestionJobStatus.failed)

        with pytest.raises(DocumentNotParsedError) as excinfo:
            async with session() as s:
                await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert excinfo.value.ingestion_job_id == ingestion.id

    async def test_parsed_document_enqueues_despite_an_old_terminal_ingestion(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id, status=DocumentStatus.parsed)
        await make_ingestion_job(document, IngestionJobStatus.completed)

        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        assert job.status is ExtractionJobStatus.queued


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
        async with fake_llm_client(extraction_output(0, 8)) as (llm, _), session() as s:
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

        assert ran is False

    async def test_completes_using_parsed_text_not_raw_bytes(self, tmp_path: Path) -> None:
        tenant_id = uuid.uuid4()
        raw_bytes = b"RAW BYTES THAT MUST NEVER REACH THE LLM"
        document = await make_document(tenant_id)
        local.save_document(str(tmp_path), tenant_id, document.sha256, raw_bytes)
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        span = (PARSED_TEXT.find("Supplier"), PARSED_TEXT.find("reports."))
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with (
            fake_llm_client(extraction_output(*span), prompt_tokens=50, completion_tokens=10) as (
                llm,
                requests,
            ),
            session() as s,
        ):
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

        assert ran is True
        async with session() as s:
            completed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert completed is not None
        assert completed.status is ExtractionJobStatus.completed
        assert completed.error is None
        assert completed.result == expected_result(*span)
        # The parsed text travelled to the LLM as user data; the stored raw
        # bytes, which diverge from it, never did.
        sent = json.loads(requests[0].content)
        user_message = sent["messages"][1]["content"]
        assert "PARSED 8.2" in user_message
        assert "RAW BYTES" not in user_message

    async def test_document_without_parsed_text_fails_without_touching_the_llm(
        self, tmp_path: Path
    ) -> None:
        # Extraction reads document_texts; an unparsed document has no row
        # (and its raw bytes are useless to the LLM), so the job fails.
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        local.save_document(str(tmp_path), tenant_id, document.sha256, b"raw bytes only")
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with fake_llm_client(extraction_output(0, 8)) as (llm, requests), session() as s:
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

        assert ran is True
        assert requests == [], "no LLM call may happen without parsed text"
        async with session() as s:
            failed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert failed is not None
        assert failed.status is ExtractionJobStatus.failed
        assert failed.result is None
        assert "parsed text" in failed.error

    async def test_invalid_citation_spans_fail_the_job_after_exactly_one_retry(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with (
            fake_llm_client_queue([extraction_output(0, 10_000), extraction_output(0, 10_000)]) as (
                llm,
                requests,
            ),
            session() as s,
        ):
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

        assert ran is True
        assert len(requests) == 2, "the gate retries once, never more"
        async with session() as s:
            failed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert failed is not None
        assert failed.status is ExtractionJobStatus.failed
        assert failed.result is None
        assert "citation" in failed.error

    async def test_valid_second_attempt_completes_after_a_rejected_first(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        span = (PARSED_TEXT.find("Supplier"), PARSED_TEXT.find("reports."))
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with (
            fake_llm_client_queue([extraction_output(0, 10_000), extraction_output(*span)]) as (
                llm,
                requests,
            ),
            session() as s,
        ):
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

        assert ran is True
        assert len(requests) == 2
        async with session() as s:
            completed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert completed is not None
        assert completed.status is ExtractionJobStatus.completed
        assert completed.result == expected_result(*span)

    async def test_llm_output_failure_marks_job_failed_not_completed(self, tmp_path: Path) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with fake_llm_client("I cannot help with that.") as (llm, _), session() as s:
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

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
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        async with session() as s:
            ran = await run_next_extraction_job(
                s,
                llm=FailingLlm(),  # type: ignore[arg-type]
                review_threshold=0.8,
            )

        assert ran is True
        async with session() as s:
            failed = await jobs_repo.find_by_id(s, tenant_id=tenant_id, job_id=job.id)
        assert failed is not None
        assert failed.status is ExtractionJobStatus.failed
        assert "llm call failed" in failed.error


class TestReviewRouting:
    """W5·A: extraction items whose Confidence falls below the threshold are
    routed to the review queue as pending items; the rest are not."""

    async def test_items_below_the_threshold_become_pending_review_items(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        span = (PARSED_TEXT.find("Supplier"), PARSED_TEXT.find("reports."))
        async with session() as s:
            job = await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        # Obligation confidence 0.3 and defined-term confidence 0.7 are both
        # below the 0.8 threshold.
        async with (
            fake_llm_client(extraction_output(*span, confidence=0.3)) as (llm, _),
            session() as s,
        ):
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.8)

        assert ran is True
        async with session() as s:
            items = (
                (await s.execute(select(ReviewItem).order_by(ReviewItem.item_type))).scalars().all()
            )
        assert [item.item_type for item in items] == ["defined_term", "obligation"]
        for item in items:
            assert item.tenant_id == tenant_id
            assert item.source is ReviewItemSource.extraction
            assert item.document_id == document.id
            assert item.job_id == job.id
            assert item.status is ReviewItemStatus.pending
            assert item.corrected_values is None
        obligation = next(item for item in items if item.item_type == "obligation")
        assert obligation.confidence == 0.3
        assert obligation.payload == {
            **expected_result(*span)["obligations"][0],
            "confidence": 0.3,
        }
        term = next(item for item in items if item.item_type == "defined_term")
        assert term.confidence == 0.7
        assert term.payload == expected_result(*span)["defined_terms"][0]

    async def test_items_at_or_above_the_threshold_are_not_routed(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_document(tenant_id)
        await seed_parsed_text(tenant_id, document.id, PARSED_TEXT)
        span = (PARSED_TEXT.find("Supplier"), PARSED_TEXT.find("reports."))
        async with session() as s:
            await enqueue_extraction(s, tenant_id=tenant_id, document_id=document.id)

        # Confidences 0.9 and 0.7: exactly at the threshold is not below it.
        async with (
            fake_llm_client(extraction_output(*span)) as (llm, _),
            session() as s,
        ):
            ran = await run_next_extraction_job(s, llm=llm, review_threshold=0.7)

        assert ran is True
        async with session() as s:
            items = (await s.execute(select(ReviewItem))).scalars().all()
        assert items == []
