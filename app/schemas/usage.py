"""Wire contracts for the admin spend surface (issue #30)."""

import uuid

from pydantic import BaseModel


class UsageSpendRow(BaseModel):
    """Spend aggregated over one group: a job kind, a job, or the total."""

    # The total row reports "" — no single job kind.
    job_type: str
    job_id: uuid.UUID | None
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


class UsageSpendResponse(BaseModel):
    rows: list[UsageSpendRow]
    total: UsageSpendRow
