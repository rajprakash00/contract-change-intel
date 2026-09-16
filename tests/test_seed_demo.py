"""Integration test for the demo tenant seed script (ADR-011): real Postgres,
the LLM wire faked at the httpx2 transport seam. Locks that seed() lands the
sample pair with a finished Change Report, that re-running a seeded tenant
spends nothing, that a partial run is repaired, and that a failed job fails
loudly instead of reporting success.
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
import pytest
from sqlalchemy import delete, select

import app.db as db
from app.config import Settings
from app.llm.client import OpenAiClient
from app.models.change_report_job import ChangeReportJob
from app.models.document import Document
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.document_text import DocumentText
from app.models.extraction_job import ExtractionJob
from app.models.ingestion_job import IngestionJob
from app.models.review_item import ReviewItem
from app.services.diffing import detect_changes
from scripts.seed_demo import seed
from tests.fake_openai import completion_body, embeddings_body, make_settings

_AGREEMENT = Path("scripts/demo_data/agreement.txt").read_text()
_AMENDMENT = Path("scripts/demo_data/amendment.txt").read_text()

# One embedding vector for every chunk row and every search query: identical
# vectors rank all chunks equally, which is enough for the demo pair.
VECTOR = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)


def _extraction_output() -> str:
    return json.dumps(
        {
            "obligations": [
                {
                    "clause_ref": "2",
                    "description": "The Client shall pay each invoice when due.",
                    "owner": "Client",
                    "citation": {"char_start": 0, "char_end": 9},
                    "confidence": 0.9,
                }
            ],
            "defined_terms": [],
        }
    )


def _contents() -> list[str]:
    """Chat answers the whole pipeline needs, in call order: extraction of
    each version, then an explanation covering every detected change, then
    the impact mapping."""
    changes = detect_changes(_AGREEMENT, _AMENDMENT)
    explanation = json.dumps(
        {
            "changes": [
                {"index": i, "description": "The payment window changes.", "severity": "medium"}
                for i in range(len(changes))
            ]
        }
    )
    impact = json.dumps({"impacts": [{"index": 0, "confidence": 0.8}]})
    return [_extraction_output(), _extraction_output(), explanation, impact]


def _wire(contents: list[str]) -> object:
    """Chat answers come from `contents` in order (last repeats); embeddings
    answer one vector per input, so any chunk count ingests cleanly."""
    chat_state = {"index": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/embeddings"):
            inputs = json.loads(request.content)["input"]
            payload = embeddings_body([VECTOR] * len(inputs))
            return httpx2.Response(200, content=json.dumps(payload).encode())
        content = contents[min(chat_state["index"], len(contents) - 1)]
        chat_state["index"] += 1
        return httpx2.Response(200, content=json.dumps(completion_body(content)).encode())

    return handler


@pytest.fixture
async def settings(tmp_path: Path) -> Settings:
    return make_settings(data_dir=str(tmp_path))


@pytest.fixture(autouse=True)
async def engine() -> AsyncIterator[None]:
    db.init_engine("postgresql+asyncpg://postgres:postgres@localhost:5433/cci")
    yield
    await db.dispose_engine()


@pytest.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    yield
    sessionmaker = db.get_sessionmaker()
    async with sessionmaker() as session:
        await session.execute(delete(ReviewItem))
        await session.execute(delete(ChangeReportJob))
        await session.execute(delete(ExtractionJob))
        await session.execute(delete(IngestionJob))
        await session.execute(delete(DocumentChunk))
        await session.execute(delete(DocumentText))
        await session.execute(delete(Document))
        await session.commit()


@asynccontextmanager
async def fake_llm(contents: list[str]) -> AsyncIterator[tuple[OpenAiClient, list[httpx2.Request]]]:
    requests: list[httpx2.Request] = []
    wire = httpx2.AsyncClient(transport=httpx2.MockTransport(_wire(contents)))
    client = OpenAiClient(make_settings(), http_client=wire)
    try:
        yield client, requests
    finally:
        await wire.aclose()


async def _tenant_documents(tenant_id: uuid.UUID) -> list[Document]:
    async with db.get_sessionmaker()() as session:
        rows = (
            (await session.execute(select(Document).where(Document.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
    return list(rows)


async def _tenant_report_jobs(tenant_id: uuid.UUID) -> list[ChangeReportJob]:
    async with db.get_sessionmaker()() as session:
        rows = (
            (
                await session.execute(
                    select(ChangeReportJob).where(ChangeReportJob.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


async def test_seed_creates_parsed_pair_with_a_completed_change_report(
    settings: Settings,
) -> None:
    tenant_id = uuid.uuid4()

    async with fake_llm(_contents()) as (llm, _requests):
        summary = await seed(tenant_id, settings, llm)

    assert summary["status"] == "seeded"
    rows = await _tenant_documents(tenant_id)
    assert len(rows) == 2
    assert all(row.status.value == "parsed" for row in rows)
    async with db.get_sessionmaker()() as session:
        chunks = (
            (
                await session.execute(
                    select(DocumentChunk).where(DocumentChunk.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        jobs = (
            (
                await session.execute(
                    select(ChangeReportJob).where(ChangeReportJob.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
    assert chunks, "ingestion wrote chunks"
    assert len(jobs) == 1
    assert jobs[0].status.value == "completed"
    assert jobs[0].result["changes"], "the report explains the diff"

    # No review items: the fake confidences sit above the default thresholds.
    async with db.get_sessionmaker()() as session:
        items = (
            (await session.execute(select(ReviewItem).where(ReviewItem.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
    assert items == []


async def test_reseeding_a_completed_tenant_spends_no_llm_calls(settings: Settings) -> None:
    tenant_id = uuid.uuid4()

    async with fake_llm(_contents()) as (llm, requests):
        first = await seed(tenant_id, settings, llm)
        after_first = len(requests)
        second = await seed(tenant_id, settings, llm)

    assert first["status"] == "seeded"
    assert second == {"status": "already_seeded", "documents": 2}
    assert len(await _tenant_documents(tenant_id)) == 2
    assert len(requests) == after_first, "the re-run spends no LLM calls"


async def test_seed_repairs_a_partial_run_that_stopped_after_uploads(
    settings: Settings,
) -> None:
    from scripts.seed_demo import _AGREEMENT_SHA256, _AMENDMENT_SHA256, _upload

    tenant_id = uuid.uuid4()
    agreement = await _upload(
        settings, tenant_id, Path("scripts/demo_data/agreement.txt"), _AGREEMENT_SHA256
    )
    await _upload(
        settings,
        tenant_id,
        Path("scripts/demo_data/amendment.txt"),
        _AMENDMENT_SHA256,
        amends_document_id=agreement.id,
    )

    async with fake_llm(_contents()) as (llm, _requests):
        summary = await seed(tenant_id, settings, llm)

    assert summary["status"] == "seeded"
    assert len(await _tenant_documents(tenant_id)) == 2, "no duplicate uploads"
    jobs = await _tenant_report_jobs(tenant_id)
    assert len(jobs) == 1
    assert jobs[0].status.value == "completed"


async def test_a_failed_seeded_job_fails_loudly_not_as_success(settings: Settings) -> None:
    tenant_id = uuid.uuid4()

    # A refusal is not valid extraction output: the job fails, and the seed
    # must surface that instead of reporting "seeded".
    async with fake_llm(["I cannot help with that."]) as (llm, _requests):
        with pytest.raises(RuntimeError, match="failed"):
            await seed(tenant_id, settings, llm)
