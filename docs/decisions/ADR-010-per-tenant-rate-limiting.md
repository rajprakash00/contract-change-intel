# ADR-010: In-Process Per-Tenant Rate Limiting on LLM-Costing Endpoints

## Context

The two LLM-enqueue POSTs (`POST /documents/{id}/extraction`,
`POST /agreements/{id}/change-report`) each authorize a job whose worker
side spends OpenAI tokens — extraction per document, change reports per
version pair. Nothing stopped one tenant from enqueueing in a loop and
running away with the shared LLM budget. The system is multi-tenant; the
worker cost accounting (`app/llm/cost.py`) tracks spend but does not gate it.

## Decision

**Per-tenant fixed-window rate limits on the two enqueue endpoints, using
the `limits` library with in-process storage.**

- **Scoped to the budget-spending surface.** Only the endpoints that
  authorize LLM work are limited — search embeds queries in the request
  path but is read-only and tenant-gated by usage patterns we accept for
  now; every other endpoint is unlimited. The checks live as FastAPI
  dependencies (`ExtractionRateLimit` / `ChangeReportRateLimit` in
  `app/api/deps.py`) resolving after `AdminPrincipal`, so a rejected role
  never spends budget and the enforced POST spends exactly one unit before
  the service runs.
- **Keyed per (kind, tenant).** The tenant comes from the token's tenant
  claim, matching every other tenant scoping in the codebase. The two
  endpoint kinds are separate budgets; neither is affected by the other's
  spend.
- **Thresholds are settings** (`rate_limit_extraction_per_hour`,
  `rate_limit_change_report_per_hour`, default 60/hour each) over a fixed
  one-hour window. The amount is part of the limiter key, so raising a
  threshold cannot resurrect a tenant's spent budget within the window.
  A value of 0 blocks all calls for that kind.
- **429 with `Retry-After`.** The failure is a domain exception
  (`RateLimitExceededError`, no HTTP semantics) mapped once in
  `errors.py` to 429, with `Retry-After` set to the window reset. Attempts
  spend budget even when the service would answer 404/409 — rate limiting
  counts requests, not successes.
- **In-process storage (MemoryStorage), deliberately.** One API replica is
  deployed today (W6·B), so a per-process counter is the whole truth.
  Budgeting per replica errs on the safe side: N replicas under-provision
  by a factor of N rather than over-provision — the failure mode is extra
  LLM spend, not silent throttling of legitimate traffic.

## Consequences

- The multi-replica path is the deliberate scaling step, not built now:
  when API replicas grow past one, the per-replica budget multiplier must
  be set on the settings knobs (divide the intended tenant budget by the
  replica count) until the counters move to shared storage. `limits`
  already has the seam for it — swap `MemoryStorage` for a Redis-backed
  storage (`limits.storage.RedisStorage`) keyed the same way; the strategy,
  keys, settings, and error mapping are unchanged. The alternative of
  building the Redis path now is rejected: it adds an infrastructure
  dependency with exactly one replica to serve.
- Limits are per tenant, not per subject: two admins of the same tenant
  share one budget, which is the intent (the tenant's LLM budget, not the
  operator's).
- The counters are not durable: a process restart resets everyone's
  budget. Acceptable for abuse protection; the accounting of actual spend
  stays with the worker's cost logging.
- The clock is wall time; a test shifts it past the window rather than
  waiting (`tests/test_rate_limiting.py`), and a reset hook drops all
  counters for test isolation.
