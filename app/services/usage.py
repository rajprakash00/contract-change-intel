"""LLM usage accounting (issue #30): per-call persistence + aggregate reads.

The sink factory is the one place that turns a call's LlmUsage into a row:
every surface that makes LLM calls hands the sink down to the leaf functions
that call the client, so the records land where the calls happen — one row
per call, matching the client's one-log-line-per-call contract. Reads
aggregate spend for the tenant, grouped per job kind or per job.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.llm_usage as usage_repo
from app.llm.client import LlmUsage, UsageSink
from app.models.llm_usage import UsageJobKind
from app.repositories.llm_usage import SpendRow
from app.request_context import current_request_id

GroupBy = Literal["job_type", "job"]


@dataclass(frozen=True)
class SpendReport:
    """One aggregate read: grouped rows plus the tenant's whole spend."""

    rows: list[SpendRow]
    total: SpendRow


def sink(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    job_type: UsageJobKind,
    job_id: uuid.UUID | None,
) -> UsageSink:
    """A UsageSink bound to one job (or the request-path surface): each call
    writes its usage row under this tenant/job, with the active request id."""

    async def record(usage: LlmUsage) -> None:
        await usage_repo.record(
            session,
            tenant_id=tenant_id,
            job_type=job_type,
            job_id=job_id,
            usage=usage,
            request_id=current_request_id(),
        )

    return record


async def spend(session: AsyncSession, *, tenant_id: uuid.UUID, group_by: GroupBy) -> SpendReport:
    """Aggregate spend for the tenant: grouped rows plus the total."""
    rows = (
        await usage_repo.spend_by_job(session, tenant_id=tenant_id)
        if group_by == "job"
        else await usage_repo.spend_by_job_type(session, tenant_id=tenant_id)
    )
    total = await usage_repo.spend_total(session, tenant_id=tenant_id)
    return SpendReport(rows=rows, total=total)
