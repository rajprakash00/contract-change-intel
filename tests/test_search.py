"""Integration tests for hybrid search (ADR-006) against real Postgres.

Chunk/document/text rows are inserted directly with controlled embeddings so
vector and full-text rankings are deterministic; the query-embedding wire is
faked at the httpx2 transport seam (tests/fake_openai), per the AGENTS.md LLM
exception.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app.config import get_settings
from app.models.document import Document
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.document_text import DocumentText
from app.repositories import document_chunks as chunks_repo
from app.repositories import document_texts as texts_repo
from app.repositories import documents as documents_repo
from app.services.search import search
from tests.fake_openai import fake_embedding_client


def unit_vector(dimension: int) -> list[float]:
    """Orthogonal unit vector: cosine distance 0 to itself, 1 to its peers."""
    vec = [0.0] * EMBEDDING_DIMENSIONS
    vec[dimension] = 1.0
    return vec


PAYMENT = unit_vector(0)
DELIVERY = unit_vector(1)
SECRET_CLAUSE = unit_vector(2)


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
async def clean_tables() -> AsyncIterator[None]:
    yield
    async with session() as s:
        await s.execute(delete(DocumentChunk))
        await s.execute(delete(DocumentText))
        await s.execute(delete(Document))
        await s.commit()


async def make_doc_with_chunks(
    tenant_id: uuid.UUID,
    *,
    filename: str,
    texts: list[str],
    vectors: list[list[float]],
) -> Document:
    """One document whose parsed text is the chunk texts joined by blank lines,
    each chunk citing its own slice — the invariant the real pipeline upholds.
    """
    parsed_text = "\n\n".join(texts)
    async with session() as s:
        document = await documents_repo.create(
            s,
            tenant_id=tenant_id,
            filename=filename,
            mime_type="text/plain",
            sha256=uuid.uuid4().hex * 2,
        )
        await texts_repo.replace(
            s, tenant_id=tenant_id, document_id=document.id, text=parsed_text, page_map=[]
        )
        spans: list[tuple[str, int, int]] = []
        cursor = 0
        for text in texts:
            spans.append((text, cursor, cursor + len(text)))
            cursor += len(text) + 2
        await chunks_repo.replace_with_embeddings(
            s,
            tenant_id=tenant_id,
            document_id=document.id,
            chunks=spans,
            embeddings=vectors,
        )
        await s.commit()
    return document


async def run_search(tenant_id: uuid.UUID, query: str, *, limit: int = 10) -> list:
    async with fake_embedding_client([unit_vector(0)]) as (llm, _), session() as s:
        return await search(s, llm=llm, tenant_id=tenant_id, query=query, limit=limit)


class TestSearchService:
    async def test_chunk_matching_the_query_embedding_is_ranked_first(self) -> None:
        tenant_id = uuid.uuid4()
        payment = await make_doc_with_chunks(
            tenant_id,
            filename="msa.docx",
            texts=["Supplier shall pay within thirty days."],
            vectors=[PAYMENT],
        )
        delivery = await make_doc_with_chunks(
            tenant_id,
            filename="sow.docx",
            texts=["Goods shall be delivered to the customer site."],
            vectors=[DELIVERY],
        )

        async with fake_embedding_client([PAYMENT]) as (llm, _), session() as s:
            hits = await search(s, llm=llm, tenant_id=tenant_id, query="payment terms", limit=10)

        assert [hit.document_id for hit in hits] == [payment.id, delivery.id]
        assert hits[0].score > hits[1].score

    async def test_exact_terms_find_chunks_the_query_vector_misses(self) -> None:
        # The chunk sits in a vector direction unrelated to the query vector,
        # but its distinctive token must surface it through the full-text half.
        tenant_id = uuid.uuid4()
        indemnity = await make_doc_with_chunks(
            tenant_id,
            filename="msa.docx",
            texts=["The supplier grants indemnification against third-party claims."],
            vectors=[SECRET_CLAUSE],
        )

        async with fake_embedding_client([unit_vector(3)]) as (llm, _), session() as s:
            hits = await search(s, llm=llm, tenant_id=tenant_id, query="indemnification", limit=10)

        assert [hit.document_id for hit in hits] == [indemnity.id]

    async def test_chunk_hit_by_both_engines_outranks_single_engine_hits(self) -> None:
        tenant_id = uuid.uuid4()
        both = await make_doc_with_chunks(
            tenant_id,
            filename="msa.docx",
            texts=["Payment is due within thirty days of invoice."],
            vectors=[PAYMENT],
        )
        vector_only = await make_doc_with_chunks(
            tenant_id,
            filename="sow.docx",
            texts=["Remuneration schedules follow the milestone calendar."],
            vectors=[DELIVERY],
        )

        async with fake_embedding_client([PAYMENT]) as (llm, _), session() as s:
            hits = await search(s, llm=llm, tenant_id=tenant_id, query="payment", limit=10)

        assert hits[0].document_id == both.id, "agreement of both engines must win"
        assert vector_only.id in {hit.document_id for hit in hits}

    async def test_hits_carry_citation_spans_into_the_parsed_text(self) -> None:
        tenant_id = uuid.uuid4()
        await make_doc_with_chunks(
            tenant_id,
            filename="msa.docx",
            texts=["Section 1: Payment", "Supplier shall pay within thirty days."],
            vectors=[PAYMENT, DELIVERY],
        )

        async with fake_embedding_client([PAYMENT]) as (llm, _), session() as s:
            hits = await search(s, llm=llm, tenant_id=tenant_id, query="payment", limit=10)

        assert hits, "the query must retrieve at least the embedding-matched chunk"
        async with session() as s:
            text_row = await texts_repo.find_by_document_id(s, document_id=hits[0].document_id)
        assert text_row is not None
        hit = hits[0]
        assert text_row.text[hit.char_start : hit.char_end] == hit.text

    async def test_other_tenants_chunks_are_never_returned(self) -> None:
        tenant_id = uuid.uuid4()
        stranger = uuid.uuid4()
        await make_doc_with_chunks(
            stranger, filename="theirs.docx", texts=["Their secret clause."], vectors=[PAYMENT]
        )

        hits = await run_search(tenant_id, "secret clause")

        assert hits == []

    async def test_limit_caps_the_number_of_hits(self) -> None:
        tenant_id = uuid.uuid4()
        await make_doc_with_chunks(
            tenant_id,
            filename="msa.docx",
            texts=["Clause one about payment.", "Clause two about payment.", "Clause three."],
            vectors=[PAYMENT, PAYMENT, DELIVERY],
        )

        async with fake_embedding_client([PAYMENT]) as (llm, _), session() as s:
            hits = await search(s, llm=llm, tenant_id=tenant_id, query="payment", limit=1)

        assert len(hits) == 1

    async def test_fusion_sees_past_the_page_size_of_a_single_engine(self) -> None:
        # A chunk ranked below the page cut by one engine must still surface
        # when the other engine ranks it first — RRF can only do that if the
        # candidate pool is deeper than the final page.
        tenant_id = uuid.uuid4()
        both = await make_doc_with_chunks(
            tenant_id,
            filename="msa.docx",
            texts=["Payment is due within thirty days."],
            vectors=[DELIVERY],
        )
        await make_doc_with_chunks(
            tenant_id,
            filename="sow.docx",
            texts=["Remuneration schedules follow the milestone calendar."],
            vectors=[PAYMENT],
        )

        async with fake_embedding_client([PAYMENT]) as (llm, _), session() as s:
            hits = await search(s, llm=llm, tenant_id=tenant_id, query="payment", limit=1)

        assert len(hits) == 1
        assert hits[0].document_id == both.id

    async def test_tenant_with_no_ingested_documents_gets_no_hits(self) -> None:
        hits = await run_search(uuid.uuid4(), "anything at all")

        assert hits == []

    async def test_hit_names_the_document_it_came_from(self) -> None:
        tenant_id = uuid.uuid4()
        document = await make_doc_with_chunks(
            tenant_id, filename="msa.docx", texts=["Payment terms apply."], vectors=[PAYMENT]
        )

        hits = await run_search(tenant_id, "payment")

        assert len(hits) == 1
        assert hits[0].document_id == document.id
        assert hits[0].filename == "msa.docx"
        assert hits[0].document_sha256 == document.sha256
