"""Integration tests for the change report service (real Postgres; LLM wire
faked at the httpx2 seam).

Enqueue is prerequisite-gated: 409 with detail naming the first missing
ingestion or extraction job on either version — the caller drives
everything explicitly (docs/w4-decisions.md). The worker handler diffs and
explains; every failure becomes a failed job row, never a raise.
"""

import json
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
import app.repositories.document_texts as texts_repo
import app.repositories.documents as documents_repo
from app.config import get_settings
from app.llm.client import LlmOutputError
from app.models.change_report_job import ChangeReportJob, ChangeReportJobStatus
from app.models.document import Document, DocumentStatus
from app.models.document_text import DocumentText
from app.models.extraction_job import ExtractionJob, ExtractionJobStatus
from app.services.change_report import (
    AmendmentMismatchError,
    ChangeReportJobNotFoundError,
    PrerequisiteMissingError,
    enqueue_change_report,
    explain_changes,
    get_change_report_job,
    run_next_change_report_job,
)
from app.services.documents import DocumentNotFoundError
from tests.fake_openai import fake_llm_client

BASE_TEXT = "2.1 Delivery\n\nLICENSOR shall deliver within 14 days."
AMENDED_TEXT = "2.1 Delivery\n\nLICENSOR shall deliver within 30 days."

EXPLANATION_OUTPUT = json.dumps(
    {"changes": [{"index": 0, "description": "The delivery window doubles.", "severity": "high"}]}
)


@pytest.fixture(autouse=True)
async def engine() -> AsyncIterator[None]:
    db.init_engine(get_settings().database_url)
    yield
    await db.dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ChangeReportJob))
        await session.execute(delete(ExtractionJob))
        await session.execute(delete(DocumentText))
        await session.execute(delete(Document))
        await session.commit()


async def make_document(
    *,
    tenant_id: uuid.UUID,
    text: str | None,
    parsed: bool,
    amends: Document | None = None,
) -> Document:
    """One document row; `text` also writes its parsed text, `parsed` flips
    the lifecycle status (a completed ingestion leaves documents parsed)."""
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        document = await documents_repo.create(
            session,
            tenant_id=tenant_id,
            filename="agreement.txt",
            mime_type="text/plain",
            sha256=uuid.uuid4().hex * 2,
            amends_document_id=amends.id if amends else None,
        )
        if text is not None:
            await texts_repo.replace(
                session,
                tenant_id=document.tenant_id,
                document_id=document.id,
                text=text,
                page_map=[],
            )
        if parsed:
            await documents_repo.set_status(session, document, DocumentStatus.parsed)
        return document


async def complete_extraction(document: Document) -> None:
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        session.add(
            ExtractionJob(
                tenant_id=document.tenant_id,
                document_id=document.id,
                status=ExtractionJobStatus.completed,
                result={},
            )
        )
        await session.commit()


async def ready_pair() -> tuple[Document, Document]:
    tenant_id = uuid.uuid4()
    base = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True)
    amended = await make_document(tenant_id=tenant_id, text=AMENDED_TEXT, parsed=True, amends=base)
    await complete_extraction(base)
    await complete_extraction(amended)
    return base, amended


async def with_session() -> AsyncIterator[AsyncSession]:
    async with db.get_sessionmaker()() as session:
        yield session


class TestEnqueueChangeReport:
    async def test_enqueues_queued_job_for_the_two_named_documents(self) -> None:
        base, amended = await ready_pair()

        async with db.get_sessionmaker()() as session:
            job = await enqueue_change_report(
                session,
                tenant_id=base.tenant_id,
                base_document_id=base.id,
                amended_document_id=amended.id,
            )

        assert job.status is ChangeReportJobStatus.queued
        assert job.base_document_id == base.id
        assert job.amended_document_id == amended.id
        assert job.result is None

    async def test_unknown_base_document_is_document_not_found(self) -> None:
        with pytest.raises(DocumentNotFoundError):
            async with db.get_sessionmaker()() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=uuid.uuid4(),
                    base_document_id=uuid.uuid4(),
                    amended_document_id=uuid.uuid4(),
                )

    async def test_unknown_amendment_document_is_document_not_found(self) -> None:
        base = await make_document(tenant_id=uuid.uuid4(), text=BASE_TEXT, parsed=True)

        with pytest.raises(DocumentNotFoundError):
            async with db.get_sessionmaker()() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=base.tenant_id,
                    base_document_id=base.id,
                    amended_document_id=uuid.uuid4(),
                )

    async def test_amendment_not_linked_to_the_base_document_is_a_mismatch(self) -> None:
        tenant_id = uuid.uuid4()
        base = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True)
        unrelated = await make_document(tenant_id=tenant_id, text=AMENDED_TEXT, parsed=True)

        with pytest.raises(AmendmentMismatchError):
            async with db.get_sessionmaker()() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=base.tenant_id,
                    base_document_id=base.id,
                    amended_document_id=unrelated.id,
                )

    async def test_unparsed_base_names_base_ingestion_with_no_job_id(self) -> None:
        tenant_id = uuid.uuid4()
        base = await make_document(tenant_id=tenant_id, text=None, parsed=False)
        amended = await make_document(
            tenant_id=tenant_id, text=AMENDED_TEXT, parsed=True, amends=base
        )
        await complete_extraction(amended)

        with pytest.raises(PrerequisiteMissingError) as exc_info:
            async with db.get_sessionmaker()() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=base.tenant_id,
                    base_document_id=base.id,
                    amended_document_id=amended.id,
                )

        missing = exc_info.value
        assert missing.document_id == base.id
        assert missing.kind == "ingestion"
        assert missing.job_id is None

    async def test_unparsed_amendment_names_amendment_ingestion_after_base_is_ready(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        base = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True)
        await complete_extraction(base)
        amended = await make_document(tenant_id=tenant_id, text=None, parsed=False, amends=base)

        with pytest.raises(PrerequisiteMissingError) as exc_info:
            async with db.get_sessionmaker()() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=base.tenant_id,
                    base_document_id=base.id,
                    amended_document_id=amended.id,
                )

        missing = exc_info.value
        assert missing.document_id == amended.id
        assert missing.kind == "ingestion"

    async def test_base_without_completed_extraction_names_base_extraction(self) -> None:
        tenant_id = uuid.uuid4()
        base = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True)
        amended = await make_document(
            tenant_id=tenant_id, text=AMENDED_TEXT, parsed=True, amends=base
        )
        await complete_extraction(amended)

        with pytest.raises(PrerequisiteMissingError) as exc_info:
            async with db.get_sessionmaker()() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=base.tenant_id,
                    base_document_id=base.id,
                    amended_document_id=amended.id,
                )

        missing = exc_info.value
        assert missing.document_id == base.id
        assert missing.kind == "extraction"
        assert missing.job_id is None

    async def test_failed_extraction_job_is_named_as_the_missing_prerequisite(
        self,
    ) -> None:
        tenant_id = uuid.uuid4()
        base = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True)
        amended = await make_document(
            tenant_id=tenant_id, text=AMENDED_TEXT, parsed=True, amends=base
        )
        sessionmaker = db.get_sessionmaker()
        async with sessionmaker() as session:
            failed = ExtractionJob(
                tenant_id=base.tenant_id,
                document_id=base.id,
                status=ExtractionJobStatus.failed,
                error="boom",
            )
            session.add(failed)
            await session.commit()
            failed_id = failed.id
        await complete_extraction(amended)

        with pytest.raises(PrerequisiteMissingError) as exc_info:
            async with sessionmaker() as session:
                await enqueue_change_report(
                    session,
                    tenant_id=base.tenant_id,
                    base_document_id=base.id,
                    amended_document_id=amended.id,
                )

        missing = exc_info.value
        assert missing.kind == "extraction"
        assert missing.job_id == failed_id


class TestGetChangeReportJob:
    async def test_returns_the_tenant_scoped_job(self) -> None:
        base, amended = await ready_pair()
        async with db.get_sessionmaker()() as session:
            job = await enqueue_change_report(
                session,
                tenant_id=base.tenant_id,
                base_document_id=base.id,
                amended_document_id=amended.id,
            )

        async with db.get_sessionmaker()() as session:
            found = await get_change_report_job(session, tenant_id=base.tenant_id, job_id=job.id)

        assert found.id == job.id

    async def test_unknown_or_foreign_job_raises_not_found(self) -> None:
        with pytest.raises(ChangeReportJobNotFoundError):
            async with db.get_sessionmaker()() as session:
                await get_change_report_job(session, tenant_id=uuid.uuid4(), job_id=uuid.uuid4())


class TestRunNextChangeReportJob:
    async def test_completes_with_diffed_and_explained_changes(self) -> None:
        base, amended = await ready_pair()
        async with db.get_sessionmaker()() as session:
            job = await enqueue_change_report(
                session,
                tenant_id=base.tenant_id,
                base_document_id=base.id,
                amended_document_id=amended.id,
            )

        async with (
            fake_llm_client(EXPLANATION_OUTPUT) as (llm, requests),
            db.get_sessionmaker()() as session,
        ):
            ran = await run_next_change_report_job(session, llm=llm)

        assert ran is True
        assert len(requests) == 1, "exactly one structured explanation call per version pair"
        async with db.get_sessionmaker()() as session:
            done = await get_change_report_job(session, tenant_id=base.tenant_id, job_id=job.id)
        assert done.status is ChangeReportJobStatus.completed
        changes = done.result["changes"]
        assert len(changes) == 1
        change = changes[0]
        assert change["kind"] == "modified"
        assert change["clause_ref"] == "2.1"
        assert change["base_span"] is not None
        assert change["amended_span"] is not None
        assert change["description"] == "The delivery window doubles."
        assert change["severity"] == "high"

    async def test_no_detected_changes_completes_without_an_llm_call(self) -> None:
        tenant_id = uuid.uuid4()
        base = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True)
        amended = await make_document(tenant_id=tenant_id, text=BASE_TEXT, parsed=True, amends=base)
        await complete_extraction(base)
        await complete_extraction(amended)
        async with db.get_sessionmaker()() as session:
            job = await enqueue_change_report(
                session,
                tenant_id=base.tenant_id,
                base_document_id=base.id,
                amended_document_id=amended.id,
            )

        async with (
            fake_llm_client(EXPLANATION_OUTPUT) as (llm, requests),
            db.get_sessionmaker()() as session,
        ):
            ran = await run_next_change_report_job(session, llm=llm)

        assert ran is True
        assert requests == []
        async with db.get_sessionmaker()() as session:
            done = await get_change_report_job(session, tenant_id=base.tenant_id, job_id=job.id)
        assert done.status is ChangeReportJobStatus.completed
        assert done.result == {"changes": []}

    async def test_llm_failure_becomes_a_failed_job_row(self) -> None:
        base, amended = await ready_pair()
        async with db.get_sessionmaker()() as session:
            job = await enqueue_change_report(
                session,
                tenant_id=base.tenant_id,
                base_document_id=base.id,
                amended_document_id=amended.id,
            )

        # Refusal content is not JSON: the structured-output gate rejects it.
        async with (
            fake_llm_client("I cannot help with that.") as (llm, _),
            db.get_sessionmaker()() as session,
        ):
            ran = await run_next_change_report_job(session, llm=llm)

        assert ran is True
        async with db.get_sessionmaker()() as session:
            failed = await get_change_report_job(session, tenant_id=base.tenant_id, job_id=job.id)
        assert failed.status is ChangeReportJobStatus.failed
        assert failed.result is None
        assert failed.error

    async def test_explanation_indices_that_do_not_match_the_changes_fail_the_job(
        self,
    ) -> None:
        base, amended = await ready_pair()
        async with db.get_sessionmaker()() as session:
            job = await enqueue_change_report(
                session,
                tenant_id=base.tenant_id,
                base_document_id=base.id,
                amended_document_id=amended.id,
            )

        mismatched = json.dumps({"changes": [{"index": 3, "description": "x", "severity": "low"}]})
        async with (
            fake_llm_client(mismatched) as (llm, _),
            db.get_sessionmaker()() as session,
        ):
            ran = await run_next_change_report_job(session, llm=llm)

        assert ran is True
        async with db.get_sessionmaker()() as session:
            failed = await get_change_report_job(session, tenant_id=base.tenant_id, job_id=job.id)
        assert failed.status is ChangeReportJobStatus.failed

    async def test_no_queued_job_reports_no_work(self) -> None:
        async with (
            fake_llm_client(EXPLANATION_OUTPUT) as (llm, _),
            db.get_sessionmaker()() as session,
        ):
            ran = await run_next_change_report_job(session, llm=llm)

        assert ran is False


class TestExplainChangesGate:
    async def test_reply_is_returned_sorted_by_index(self) -> None:
        from app.services.diffing import detect_changes

        base = "1. A\n\nAlpha.\n\n2. B\n\nBeta."
        amended = "1. A\n\nAlpha changed.\n\n2. B\n\nBeta changed."
        changes = detect_changes(base, amended)
        reply = json.dumps(
            {
                "changes": [
                    {"index": 1, "description": "b", "severity": "low"},
                    {"index": 0, "description": "a", "severity": "high"},
                ]
            }
        )

        async with fake_llm_client(reply) as (llm, _):
            explanations = await explain_changes(
                llm, changes=changes, base_text=base, amended_text=amended
            )

        assert [e.index for e in explanations] == [0, 1]

    async def test_explanations_not_covering_every_change_are_rejected(self) -> None:
        from app.services.diffing import detect_changes

        base = "1. A\n\nAlpha.\n\n2. B\n\nBeta."
        amended = "1. A\n\nAlpha changed.\n\n2. B\n\nBeta changed."
        changes = detect_changes(base, amended)
        partial = json.dumps({"changes": [{"index": 0, "description": "a", "severity": "low"}]})

        async with fake_llm_client(partial) as (llm, _):
            with pytest.raises(LlmOutputError):
                await explain_changes(llm, changes=changes, base_text=base, amended_text=amended)
