"""Per-LLM-call usage accounting: tokens, cost, and latency persisted per
call, matching the client's one-log-line-per-call contract (issue #30).

Append-only accounting rows; reads are aggregates over them (spend per
tenant, job kind, or job).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UsageJobKind(enum.Enum):
    """Which job kind (or synchronous surface) produced the call.

    No FK on purpose: each job kind is its own table, and this column only
    names which one job_id points into — None for surfaces without a job
    row, like the search request path.
    """

    ingestion = "ingestion"
    extraction = "extraction"
    change_report = "change_report"
    search = "search"


class LlmUsageRecord(Base):
    __tablename__ = "llm_usage"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Tenant + time indexed together: the read surface aggregates spend over
    # time ranges per tenant, so one composite index serves it.
    tenant_id: Mapped[uuid.UUID]
    job_type: Mapped[UsageJobKind] = mapped_column(
        Enum(UsageJobKind, name="llm_usage_job_type", native_enum=True)
    )
    job_id: Mapped[uuid.UUID | None]
    model: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    # An estimate from per-1M-token list prices (app/llm/cost.py), not a bill.
    cost_usd: Mapped[float] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer)
    # Correlates the row with the request that produced it ('' if none).
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_llm_usage_tenant_id_created_at", "tenant_id", "created_at"),)
