"""Insert-only writes + aggregate reads over the per-call LLM usage table."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_usage import LlmUsageRecord, UsageJobKind


@dataclass(frozen=True)
class SpendRow:
    """Aggregated spend over one group: calls, tokens, cost, and latency.

    job_type/job_id name the group — job_id is None for the per-kind and
    total groupings and for calls made outside any job (the search surface);
    the total row's job_type is ''.
    """

    job_type: str
    job_id: uuid.UUID | None
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


async def record(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_type: UsageJobKind,
    job_id: uuid.UUID | None,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    latency_ms: int,
    request_id: str,
) -> None:
    session.add(
        LlmUsageRecord(
            tenant_id=tenant_id,
            job_type=job_type,
            job_id=job_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            request_id=request_id,
        )
    )
    await session.commit()


async def spend_by_job_type(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[SpendRow]:
    """Spend per job kind (kind declaration order), whole tenant."""
    result = await session.execute(
        select(LlmUsageRecord.job_type, *_SPEND_TOTALS)
        .where(LlmUsageRecord.tenant_id == tenant_id)
        .group_by(LlmUsageRecord.job_type)
        .order_by(LlmUsageRecord.job_type)
    )
    return [_spend_row(kind=row[0].value, job_id=None, totals=row[1:]) for row in result.all()]


async def spend_by_job(session: AsyncSession, *, tenant_id: uuid.UUID) -> list[SpendRow]:
    """Spend per job (kind + id); request-path calls group under job_id None."""
    result = await session.execute(
        select(LlmUsageRecord.job_type, LlmUsageRecord.job_id, *_SPEND_TOTALS)
        .where(LlmUsageRecord.tenant_id == tenant_id)
        .group_by(LlmUsageRecord.job_type, LlmUsageRecord.job_id)
        .order_by(LlmUsageRecord.job_type, LlmUsageRecord.job_id)
    )
    return [_spend_row(kind=row[0].value, job_id=row[1], totals=row[2:]) for row in result.all()]


async def spend_total(session: AsyncSession, *, tenant_id: uuid.UUID) -> SpendRow:
    """The tenant's whole spend, one row."""
    result = await session.execute(
        select(*_SPEND_TOTALS).where(LlmUsageRecord.tenant_id == tenant_id)
    )
    return _spend_row(kind="", job_id=None, totals=result.one())


# Shared aggregate expressions: count, token sums, cost sum, latency sum.
_SPEND_TOTALS: tuple[Any, ...] = (
    func.count(),
    func.coalesce(func.sum(LlmUsageRecord.prompt_tokens), 0),
    func.coalesce(func.sum(LlmUsageRecord.completion_tokens), 0),
    func.coalesce(func.sum(LlmUsageRecord.cost_usd), 0.0),
    func.coalesce(func.sum(LlmUsageRecord.latency_ms), 0),
)


def _spend_row(*, kind: str, job_id: uuid.UUID | None, totals: Sequence[Any]) -> SpendRow:
    calls, prompt_tokens, completion_tokens, cost_usd, latency_ms = totals
    return SpendRow(
        job_type=kind,
        job_id=job_id,
        calls=int(calls),
        prompt_tokens=int(prompt_tokens),
        completion_tokens=int(completion_tokens),
        cost_usd=float(cost_usd),
        latency_ms=int(latency_ms),
    )
