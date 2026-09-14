"""Hybrid search fused with Reciprocal Rank Fusion (ADR-006).

Two Postgres-native rankings — pgvector cosine distance and English full-text
ts_rank — are fetched per query and merged here. RRF is rank-based, so the
engines' incommensurable scores never need normalizing onto one scale; the k
constant is fixed by ADR-006. The query itself is embedded in the request path
(search is the first synchronous LLM surface), so LlmErrors map to 502/503 via
the app-wide error table.
"""

import uuid
from collections.abc import Hashable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

import app.repositories.document_chunks as chunks_repo
from app.llm.client import OpenAiClient, UsageSink

# ADR-006: fixed, not tunable, until eval numbers justify a change.
RRF_K = 60

# Each engine is asked for more candidates than the final page: RRF can push
# a chunk to the top by agreeing across engines even when one engine ranked
# it below the cut, so fetching only `limit` per engine would cap recall.
_CANDIDATE_DEPTH_FACTOR = 2


def rrf_fuse[S: Hashable](rankings: Sequence[Sequence[S]], k: int) -> list[tuple[S, float]]:
    """Fuse ranked lists into one, best first: each item scores
    sum(1 / (k + rank)) across the lists that contain it (rank is 1-based).

    Ties keep first-appearance order so equal scores never shuffle between
    runs — eval regressions must be attributable to the code, not sort noise.
    """
    scores: dict[S, float] = {}
    first_seen: dict[S, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            first_seen.setdefault(item, len(first_seen))
    ordered = sorted(scores, key=lambda item: (-scores[item], first_seen[item]))
    return [(item, scores[item]) for item in ordered]


@dataclass(frozen=True)
class SearchHit:
    """One retrieved chunk with its citation span and fused RRF score.

    `char_start`/`char_end` are char offsets into the document's parsed text
    (the citation coordinate system); `text` always equals that slice.
    """

    document_id: uuid.UUID
    document_sha256: str
    filename: str
    chunk_id: uuid.UUID
    ordinal: int
    text: str
    char_start: int
    char_end: int
    score: float


async def search(
    session: AsyncSession,
    *,
    llm: OpenAiClient,
    tenant_id: uuid.UUID,
    query: str,
    limit: int,
    usage_sink: UsageSink | None = None,
) -> list[SearchHit]:
    """Hybrid search over one tenant's corpus (ADR-006): embed the query, rank
    chunks by vector similarity and by full-text match, fuse both rankings with
    RRF, and return the top `limit` as citation-spanned hits.

    Cross-document by design: impact mapping must recall obligations across the
    tenant's whole corpus, not just within one document. Raises LlmCallError /
    LlmNotConfiguredError from the query embedding; the app-wide error table
    maps those to 502/503.
    """
    return await _hybrid_hits(
        session,
        llm=llm,
        tenant_id=tenant_id,
        document_id=None,
        query=query,
        limit=limit,
        usage_sink=usage_sink,
    )


async def search_document(
    session: AsyncSession,
    *,
    llm: OpenAiClient,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    query: str,
    limit: int,
    usage_sink: UsageSink | None = None,
) -> list[SearchHit]:
    """Hybrid search restricted to one document's chunks (W4·D): the variant
    impact mapping needs — a Change recalls obligations from the base
    version only, while `GET /search` stays tenant-wide.

    Same fusion and error behavior as `search`.
    """
    return await _hybrid_hits(
        session,
        llm=llm,
        tenant_id=tenant_id,
        document_id=document_id,
        query=query,
        limit=limit,
        usage_sink=usage_sink,
    )


async def _hybrid_hits(
    session: AsyncSession,
    *,
    llm: OpenAiClient,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID | None,
    query: str,
    limit: int,
    usage_sink: UsageSink | None = None,
) -> list[SearchHit]:
    embed_reply = await llm.embed([query])
    if usage_sink is not None:
        await usage_sink(embed_reply.usage)
    (query_embedding,) = embed_reply.vectors
    depth = limit * _CANDIDATE_DEPTH_FACTOR
    vector_ranked = await chunks_repo.rank_by_similarity(
        session,
        tenant_id=tenant_id,
        embedding=query_embedding,
        limit=depth,
        document_id=document_id,
    )
    fts_ranked = await chunks_repo.rank_by_full_text(
        session, tenant_id=tenant_id, query=query, limit=depth, document_id=document_id
    )
    by_id = {chunk.id: (chunk, document) for chunk, document in [*vector_ranked, *fts_ranked]}
    fused = rrf_fuse(
        [
            [chunk.id for chunk, _ in vector_ranked],
            [chunk.id for chunk, _ in fts_ranked],
        ],
        k=RRF_K,
    )[:limit]
    hits: list[SearchHit] = []
    for chunk_id, score in fused:
        chunk, document = by_id[chunk_id]
        hits.append(
            SearchHit(
                document_id=document.id,
                document_sha256=document.sha256,
                filename=document.filename,
                chunk_id=chunk.id,
                ordinal=chunk.ordinal,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                score=score,
            )
        )
    return hits
