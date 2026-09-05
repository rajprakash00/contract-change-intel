import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from app.models.review_item import ReviewItemSource, ReviewItemStatus


class ReviewItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    source: ReviewItemSource
    item_type: str
    document_id: uuid.UUID
    job_id: uuid.UUID
    payload: dict[str, Any]
    confidence: float
    status: ReviewItemStatus
    corrected_values: dict[str, Any] | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReviewItemsResponse(BaseModel):
    items: list[ReviewItemRead]


class ReviewDispositionCreate(BaseModel):
    """POST /review-items/{id}/disposition body: the Disposition plus, for
    `edited`, the corrected values that replace the recorded payload."""

    disposition: Literal["approved", "edited", "rejected"]
    corrected_values: dict[str, Any] | None = None

    @model_validator(mode="after")
    def corrected_values_pair_with_the_disposition(self) -> "ReviewDispositionCreate":
        if self.disposition == "edited" and self.corrected_values is None:
            raise ValueError("edited resolution requires corrected_values")
        if self.disposition != "edited" and self.corrected_values is not None:
            raise ValueError(f"{self.disposition} resolution must not carry corrected_values")
        return self
