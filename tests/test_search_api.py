"""Integration tests for GET /search: the HTTP surface of hybrid search.

Real Postgres behind the ASGI transport; the query-embedding wire is faked at
the httpx2 transport seam. Error-mapping tests lock the app-wide table's
502/503 behaviour on the first synchronous LLM surface.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app.api.deps import get_llm_client
from app.config import Settings, get_settings
from app.llm.client import OpenAiClient
from app.main import app
from app.models.document import Document
from app.models.document_chunk import EMBEDDING_DIMENSIONS, DocumentChunk
from app.models.document_text import DocumentText
from app.repositories import document_chunks as chunks_repo
from app.repositories import document_texts as texts_repo
from app.repositories import documents as documents_repo
from tests.fake_jwks import bearer
from tests.fake_openai import fake_embedding_client, make_settings

TENANT = uuid.uuid4()


def unit_vector(dimension: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIMENSIONS
    vec[dimension] = 1.0
    return vec


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
    app.dependency_overrides.clear()


async def seed_one_chunk() -> uuid.UUID:
    """One tenant document with a single ingested chunk; returns the chunk id."""
    text = "Supplier shall pay within thirty days."
    async with session() as s:
        document = await documents_repo.create(
            s,
            tenant_id=TENANT,
            filename="msa.docx",
            mime_type="text/plain",
            sha256=uuid.uuid4().hex * 2,
        )
        await texts_repo.replace(
            s, tenant_id=TENANT, document_id=document.id, text=text, page_map=[]
        )
        rows = await chunks_repo.replace_with_embeddings(
            s,
            tenant_id=TENANT,
            document_id=document.id,
            chunks=[(text, 0, len(text))],
            embeddings=[unit_vector(0)],
        )
        await s.commit()
    return rows[0].id


def override_llm_with_query_vector(vector: list[float]) -> None:
    async def override() -> AsyncIterator[OpenAiClient]:
        async with fake_embedding_client([vector]) as (llm, _):
            yield llm

    app.dependency_overrides[get_llm_client] = override


async def get(path: str, *, params: dict[str, str] | None = None, tenant: uuid.UUID = TENANT):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        return await http.get(path, params=params, headers=bearer(tenant))


class TestGetSearch:
    async def test_returns_fused_hits_with_citation_spans(self) -> None:
        chunk_id = await seed_one_chunk()
        override_llm_with_query_vector(unit_vector(0))

        response = await get("/search", params={"q": "payment"})

        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        hit = body["items"][0]
        assert hit["chunk_id"] == str(chunk_id)
        assert hit["text"] == "Supplier shall pay within thirty days."
        assert hit["char_start"] == 0
        assert hit["char_end"] == len("Supplier shall pay within thirty days.")
        assert hit["score"] > 0.0
        assert hit["filename"] == "msa.docx"
        assert hit["document_sha256"]

    async def test_other_tenants_chunks_are_never_returned(self) -> None:
        await seed_one_chunk()
        override_llm_with_query_vector(unit_vector(0))

        response = await get("/search", params={"q": "payment"}, tenant=uuid.uuid4())

        assert response.status_code == 200
        assert response.json()["items"] == []

    async def test_missing_query_parameter_is_unprocessable(self) -> None:
        override_llm_with_query_vector(unit_vector(0))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            response = await http.get("/search", headers=bearer(TENANT))

        assert response.status_code == 422

    async def test_empty_query_parameter_is_unprocessable(self) -> None:
        override_llm_with_query_vector(unit_vector(0))

        response = await get("/search", params={"q": ""})

        assert response.status_code == 422

    async def test_missing_bearer_token_is_unauthorized(self) -> None:
        override_llm_with_query_vector(unit_vector(0))

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
            response = await http.get("/search", params={"q": "payment"})

        assert response.status_code == 401

    async def test_limit_is_capped_at_fifty(self) -> None:
        override_llm_with_query_vector(unit_vector(0))

        response = await get("/search", params={"q": "payment", "limit": "51"})

        assert response.status_code == 422

    async def test_unconfigured_openai_key_maps_to_503(self) -> None:
        # No LLM override: the real dep constructs OpenAiClient from settings,
        # which raises LlmNotConfiguredError on an empty key — a deployment
        # problem, mapped app-wide to 503.
        async def empty_key_settings() -> Settings:
            return make_settings(openai_api_key="")

        app.dependency_overrides[get_settings] = empty_key_settings

        response = await get("/search", params={"q": "payment"})

        assert response.status_code == 503

    async def test_embedding_wire_failure_maps_to_502(self) -> None:
        # A failed query embed must surface as 502 through the app-wide error
        # table, not an unhandled 500.
        wire = httpx2.AsyncClient(
            transport=httpx2.MockTransport(lambda request: httpx2.Response(500, content=b"boom"))
        )
        llm = OpenAiClient(make_settings(), http_client=wire)

        async def override() -> AsyncIterator[OpenAiClient]:
            yield llm

        app.dependency_overrides[get_llm_client] = override

        response = await get("/search", params={"q": "payment"})

        assert response.status_code == 502
