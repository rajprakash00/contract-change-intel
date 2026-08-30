# ADR-004: Postgres-backed job rows for LLM work (no task queue)

## Context

W2·B adds the first LLM HTTP surface (obligation extraction). The LLM call
must never sit in the request path: calls take seconds to tens of seconds,
and failures need a durable, inspectable record. PLAN.md's delivery model
names "Postgres-backed job table + worker process (no Celery)" but the
mechanics were undecided.

## Decision

Background work is a row in a `*_jobs` table (`extraction_jobs` first), and
the API only ever writes `queued` rows. A separate worker process
(`python -m app.worker`) claims and runs them:

- **Claim**: `SELECT … FOR UPDATE SKIP LOCKED`, oldest first, flipped to
  `running` in the same transaction. Concurrent workers each get a different
  row; no distributed lock, no broker.
- **Idempotent-ish handler**: only `queued` rows are ever claimed, so a
  completed job is never re-run by the loop.
- **Failures are data**: the handler converts every failure (missing bytes,
  unsupported mime type, `LlmError`) into a `failed` row with a short reason,
  never a raise — one bad job cannot stop the loop. Result payloads are
  JSONB (`{"obligations": [...]}`), status is polled via
  `GET /extraction-jobs/{id}`.

Consequences:

- No new infrastructure: the same Postgres, same Alembic migrations, same
  sessions as the API.
- Known gap: a worker crash mid-run leaves the row `running` forever. Retry
  policy (requeue stale rows, attempt counters, dead-letter) is deferred to
  the W3 ingestion pipeline, which must define it for its own jobs anyway.
- Long-polling clients would be nicer than `GET` polling; postponed until a
  UI exists to need it.

## Rejected alternative

Celery/Redis (or any broker). Rejected because it adds a second stateful
system to operate before there is a scaling need, and job state would live
outside the database that already holds the documents and audit trail —
worse for the auditability this product exists to provide.
