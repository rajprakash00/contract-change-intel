# ADR-002: Offset pagination for document lists (cursors deferred)

## Context

`GET /documents` needs pagination. The realistic page sizes during inital weeks
are tens of rows per tenant; document lists only grow meaningfully once the
ingestion pipeline lands and evals measure real volumes.

## Decision

Use `limit`/`offset` with a `total` count in the response envelope, newest
first with id tiebreak. Revisit when eval data shows tenant with large
list sizes where deep offsets hurt (rule of thumb: consistent p95 latency 
regression on the list endpoint), or when stable iteration under concurrent
writes becomes a product requirement.

Consequences:

- **Simple, stateless, jump-to-page capable**; total count supports UI paging.
- Deep `OFFSET` scans degrade linearly and **pages can shift under concurrent
  inserts/deletes** - document might appear twice or get skipped - both 
  acceptable now, both reasons to revisit.

## Rejected alternative

Keyset/cursor pagination now. Rejected as premature: no measured need, and it
would complicate the wire contract (opaque cursors in API contracts) before 
the access patterns justify it.
