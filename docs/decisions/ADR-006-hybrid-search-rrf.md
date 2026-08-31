# ADR-006: Hybrid search — pgvector + Postgres full-text, fused with RRF

## Context

Retrieval (W3) must serve the impact-mapping work (W4–W5): given a change,
find the obligations it touches. Contracts contain both paraphrasable prose
("the supplier shall remedy defects…") and exact matchable tokens (defined
terms, clause numbers, amounts, dates). Pure vector search misses exact
tokens; pure full-text misses paraphrase.

## Decision

Hybrid search over two Postgres-native indexes, fused with Reciprocal Rank
Fusion (RRF):

- **Vector**: pgvector with an HNSW index, embeddings from OpenAI
  `text-embedding-3-small` (1536-dim) computed in the ingestion worker.
- **Full-text**: a `tsvector` column + GIN index on chunk text.
- **Fusion**: RRF — rank-based, so the two engines' incommensurable scores
  never need normalizing onto one scale. The RRF k constant is fixed (60).
- **Surface**: `GET /search?q=` — tenant-scoped, cross-document, because
  impact mapping must recall obligations across the tenant's corpus, not just
  within one document.

The pgvector extension lands as a migration; docker-compose swaps to the
`pgvector/pgvector:pg17` image. HNSW parameters stay at library defaults until
eval numbers justify tuning.

## Consequences

- One new dependency (the extension) but no new infrastructure: same Postgres,
  same Alembic flow, same compose stack.
- The search API contract (query param, tenant scoping, cross-document) is
  locked early; changing shape later breaks callers.
- Index builds happen synchronously in the ingestion worker; embedding cost
  (~$0.02/M tokens with `3-small`) is logged per call like every other LLM
  cost.

## Rejected alternative

Weighted score blending — requires normalizing cosine similarity and full-text
rank onto a common scale, which is brittle and needs per-corpus tuning. Pure
vector search rejected for the exact-match misses above; pure full-text for
paraphrase misses.
