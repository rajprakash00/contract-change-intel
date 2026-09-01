import uuid

from pydantic import BaseModel, ConfigDict


class SearchHitRead(BaseModel):
    """One retrieved chunk: citation span into the document's parsed text,
    plus the document coordinates (id, sha256, filename) a reviewer needs to
    land on the source, and the fused RRF score.
    """

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    document_sha256: str
    filename: str
    chunk_id: uuid.UUID
    ordinal: int
    text: str
    char_start: int
    char_end: int
    score: float


class SearchResponse(BaseModel):
    items: list[SearchHitRead]
