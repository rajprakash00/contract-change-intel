# Progress

State: week 1 complete (W1·A foundations, W1·B read paths, W1·C hardening + gate),
**W2·A LLM reliability foundations** (OpenAI settings, thin client wrapper,
structured-outputs skeleton, evals placeholder), and **W2·B LLM calling + eval
baseline** (extraction HTTP surface behind a Postgres job row + worker, streaming,
tool-calling skeleton, LlmError HTTP mapping); ruff/mypy clean, 78
integration+unit tests green. Remaining W2 items: first golden records (blocked on
real documents), Anthropic SDK spike (blocked on a real API key).

## Map

- `app/config.py` — Settings (.env): `database_url` (host port **5433**), `data_dir`,
  `max_upload_mb`, `log_level`
- `app/db.py` — engine/sessionmaker lifecycle owned by lifespan; `get_session` dep
- `app/main.py` — `create_app()`; lifespan, mounts route routers, error handlers
- `app/middleware.py` — pure-ASGI request-ID middleware (echo/sanitize/generate,
  response header + access log)
- `app/request_context.py` — leaf module holding `request_id_ctx`; shared by
  middleware, logging filter, and services (audit correlation)
- `app/logging_config.py` — root logging + `RequestIdFilter` (`request_id=` on every line)
- `app/api/deps.py` — shared deps (`SessionDep`, `SettingsDep`, tenant `Header`)
- `app/api/routes/documents.py` — POST upload; GET list (`limit`/`offset` page
  envelope), GET by id, GET `/content` download, DELETE
- `app/api/routes/health.py` — `GET /healthz` probe
- `app/models/` — ORM: `Document`, `DocumentStatus`, `AuditLog` (append-only)
- `app/schemas/` — Pydantic wire contracts (`DocumentRead`, `DocumentListPage`, conflict detail)
- `app/repositories/documents.py` — create, find_by_sha256/id, list_page,
  count_for_tenant, delete
- `app/repositories/audit_log.py` — insert-only `record()`
- `app/services/documents.py` — upload/read/list/file-resolve/delete flows, magic-byte
  `sniff_mime`, domain exceptions (see PLAN Architecture)
- `app/storage/local.py` — content-addressed files `{data_dir}/{tenant_id}/{sha256}`;
  save/path/delete
- `app/llm/client.py` — thin OpenAI wrapper (only module importing the SDK):
  settings-driven timeout/retries, SDK-delegated 429 backoff, `LlmError`
  hierarchy (`LlmNotConfiguredError`/`LlmCallError`/`LlmOutputError`), one
  structured `llm call` log line per call (tokens, cost, latency),
  `stream_complete()` (delta streaming, usage logged at stream end),
  `complete_with_tools()` + `LlmTool` (tool-calling skeleton, bounded loop,
  read-only-by-contract handlers — rules in `docs/llm-boundaries.md`)
- `app/llm/cost.py` — pure token→USD math; pricing table locked by unit tests
- `app/services/extraction.py` — structured-outputs skeleton: `ObligationExtraction`
  schema + `extract_obligations()`; job lifecycle: `enqueue_extraction` (queued
  row only — no LLM in the request path), `get_extraction_job`,
  `run_next_extraction_job` (worker-side claim+run; every failure becomes a
  failed row); prompt-injection boundary in `docs/llm-boundaries.md`
- `app/models/extraction_job.py` + `app/repositories/extraction_jobs.py` —
  job rows; claim via `FOR UPDATE SKIP LOCKED` (ADR-004)
- `app/api/routes/extraction.py` — `POST /documents/{id}/extraction` → 202
  queued job; `GET /extraction-jobs/{id}` polls status/result (tenant-scoped)
- `app/worker.py` — worker process (`python -m app.worker`): fails fast
  without an API key, claims queued extraction jobs, polls when idle
- `app/errors.py` — domain exception → 415/413/409/404/502/503 mapping,
  registered once (LlmError → 502/503 ready for future sync surfaces)
- `evals/` — golden-record placeholder; JSONL format decision in `evals/README.md`
- `docs/decisions/` — ADR-001 content-addressed storage; ADR-002 offset pagination;
  ADR-003 direct OpenAI SDK (no LLM framework); ADR-004 Postgres job rows
- `alembic.ini` + `migrations/` — async Alembic; `documents`, `audit_log`
- `Dockerfile` — multi-stage (uv builder → slim runtime, non-root); compose `app`
  service on :8000 with `uploads` volume; migrate via `docker compose run --rm app alembic upgrade head`
- `.github/workflows/ci.yml` — ruff, mypy, pytest against real Postgres + image-build job
- `docs/decisions/` — ADR-001 content-addressed storage; ADR-002 offset pagination

Constraints:

- Host port 5432 is occupied by an unrelated running stack — do not stop it; use 5433.
- Git staging/commits are handled by the owner, not tooling.

## Commands

```sh
docker compose up -d --wait
uv run alembic upgrade head   # tests run this automatically via conftest
uv run pytest
uv run uvicorn app.main:app --reload
```

Upload contract: multipart `file` + `X-Tenant-Id` header → 201 `{id, tenant_id,
filename, mime_type, sha256, status}`; errors: 409 duplicate bytes in tenant
(`{existing_id}`), 413 over size cap, 415 mime outside allow-list **or declared
type contradicted by magic bytes** (`sniff_mime`), 422 missing header.
Successful upload/delete append an `audit_log` row correlated to `X-Request-ID`.

Read/delete contract (all scoped by `X-Tenant-Id`; unknown id or other tenant's
row reads the same → 404 `{detail}`):
`GET /documents?limit=&offset=` → `{items[], total, limit, offset}`, newest first,
limit ≤ 100; `GET /documents/{id}` → `DocumentRead`;
`GET /documents/{id}/content` → stored bytes (`Content-Disposition` filename);
`DELETE /documents/{id}` → 204, removes row then file best-effort.
Every response carries `X-Request-ID` (echoed when sane, else generated) and
every log line carries the same id.

## Next (post-W2·B — W3 retrieval + evals)

1. Ingestion pipeline on the job-table worker: chunking, metadata, embeddings
   into pgvector, hybrid search (vector + full-text), citation spans. Retry
   policy for stale `running` job rows lands here (see ADR-004 known gap).
2. First golden records in `evals/golden/` once real documents exist; cost math
   extended to any new models before first use.
3. Anthropic SDK comparison spike (ADR-003) — same wrapper seam, real calls
   (needs a live `ANTHROPIC_API_KEY`; deferred to the owner).
4. First call with a real `OPENAI_API_KEY` still unverified (LLM tests run
   against a fake httpx2 transport).

Open: auth deferred to multi-tenancy work; DELETE has no retention window yet;
audit_log retention/read APIs deferred until review-queue work; CI green
locally, first GitHub Actions run still unverified.
