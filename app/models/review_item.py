"""Review items (W5·A): low-confidence LLM output routed to human review.

Workers create items when Confidence falls below the per-job-kind threshold
(settings); reviewers resolve them over the API. The state machine is flat —
pending → approved | edited | rejected — so every resolution is terminal and
`edited` captures corrected values instead of looping the item back.
"""

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ReviewItemSource(enum.Enum):
    extraction = "extraction"
    impact_mapping = "impact_mapping"


class ReviewItemStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    edited = "edited"
    rejected = "rejected"


class ReviewItem(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source: Mapped[ReviewItemSource] = mapped_column(
        Enum(ReviewItemSource, name="review_item_source", native_enum=True)
    )
    # The wire shape of the item under review ("obligation" / "defined_term" /
    # "impact"), so the reviewer UI knows what it is rendering.
    item_type: Mapped[str] = mapped_column(String(32))
    # The document the item concerns: the extracted document for extraction,
    # the base version for impact mappings.
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"))
    # The job that produced the item. No FK on purpose: extraction jobs and
    # change report jobs are separate tables, and the source column already
    # says which one job_id points into.
    job_id: Mapped[uuid.UUID]
    # The item exactly as the worker recorded it (wire shape).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[ReviewItemStatus] = mapped_column(
        Enum(ReviewItemStatus, name="review_item_status", native_enum=True),
        default=ReviewItemStatus.pending,
    )
    # Corrected values captured by an `edited` resolution; None otherwise.
    corrected_values: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
