"""Integration tests for the admin spend endpoint (issue #30): the tenant's
per-call usage rows, aggregated per job kind or per job. Non-admin
principals are refused with 403; the read is scoped to the caller's tenant.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app.config import get_settings
from app.models.llm_usage import LlmUsageRecord, UsageJobKind
from app.repositories import llm_usage as usage_repo
from tests.fake_jwks import bearer


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
        await s.execute(delete(LlmUsageRecord))
        await s.commit()


async def seed_call(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_type: UsageJobKind,
    job_id: uuid.UUID | None = None,
    model: str = "gpt-4o-mini",
    prompt_tokens: int = 100,
    completion_tokens: int = 20,
    cost_usd: float = 0.01,
    latency_ms: int = 250,
) -> None:
    await usage_repo.record(
        session,
        tenant_id=tenant_id,
        job_type=job_type,
        job_id=job_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        request_id="",
    )


async def seed_spend(tenant_id: uuid.UUID, *, other: uuid.UUID) -> None:
    """Extraction calls on one job, one ingestion call, one search call, and
    one other tenant's extraction call."""
    job_id = uuid.uuid4()
    async with session() as s:
        for _ in range(2):
            await seed_call(s, tenant_id=tenant_id, job_type=UsageJobKind.extraction, job_id=job_id)
        await seed_call(
            s,
            tenant_id=tenant_id,
            job_type=UsageJobKind.ingestion,
            job_id=None,
            model="text-embedding-3-small",
            prompt_tokens=120,
            completion_tokens=0,
            cost_usd=0.002,
            latency_ms=40,
        )
        await seed_call(
            s,
            tenant_id=tenant_id,
            job_type=UsageJobKind.search,
            job_id=None,
            model="text-embedding-3-small",
            prompt_tokens=1,
            completion_tokens=0,
            cost_usd=0.000001,
            latency_ms=40,
        )
        await seed_call(
            s,
            tenant_id=other,
            job_type=UsageJobKind.extraction,
            job_id=uuid.uuid4(),
            prompt_tokens=999,
            completion_tokens=999,
            cost_usd=9.99,
            latency_ms=999,
        )


async def get(client: AsyncClient, *, tenant: uuid.UUID, role: str = "admin", **params: str):
    return await client.get("/usage/spend", params=params, headers=bearer(tenant, role=role))


class TestGetUsageSpend:
    async def test_admin_reads_spend_per_job_kind(self, client: AsyncClient) -> None:
        tenant, other = uuid.uuid4(), uuid.uuid4()
        await seed_spend(tenant, other=other)

        response = await get(client, tenant=tenant)

        assert response.status_code == 200
        body = response.json()
        assert [(row["job_type"], row["calls"]) for row in body["rows"]] == [
            ("ingestion", 1),
            ("extraction", 2),
            ("search", 1),
        ]
        extraction = body["rows"][1]
        assert extraction["job_id"] is None, "job-kind grouping has no single job"
        assert extraction["prompt_tokens"] == 200
        assert extraction["completion_tokens"] == 40
        assert extraction["cost_usd"] == pytest.approx(0.02)
        assert extraction["latency_ms"] == 500
        total = body["total"]
        assert total["calls"] == 4
        assert total["cost_usd"] == pytest.approx(0.022001)

    async def test_admin_reads_spend_per_job(self, client: AsyncClient) -> None:
        tenant, other = uuid.uuid4(), uuid.uuid4()
        await seed_spend(tenant, other=other)

        response = await get(client, tenant=tenant, group_by="job")

        assert response.status_code == 200
        rows = response.json()["rows"]
        assert [(row["job_type"], row["job_id"] is None, row["calls"]) for row in rows] == [
            ("ingestion", True, 1),
            ("extraction", False, 2),
            ("search", True, 1),
        ]

    async def test_spend_read_is_tenant_scoped(self, client: AsyncClient) -> None:
        tenant, other = uuid.uuid4(), uuid.uuid4()
        await seed_spend(tenant, other=other)

        response = await get(client, tenant=other)

        assert response.status_code == 200
        body = response.json()
        assert body["total"]["calls"] == 1
        assert all(row["job_type"] == "extraction" for row in body["rows"])

    async def test_non_admin_principal_gets_403(self, client: AsyncClient) -> None:
        tenant = uuid.uuid4()

        response = await get(client, tenant=tenant, role="reviewer")

        assert response.status_code == 403
