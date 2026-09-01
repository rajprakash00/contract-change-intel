# Progress

State: week 1 complete (W1·A foundations, W1·B read paths, W1·C hardening + gate),
**W2·A LLM reliability foundations** (OpenAI settings, thin client wrapper,
structured-outputs skeleton, evals placeholder), **W2·B LLM calling + eval
baseline** (extraction HTTP surface behind a Postgres job row + worker, streaming,
tool-calling skeleton, LlmError HTTP mapping), **W3·A ingestion schema +
parsers + chunker** (pgvector/document_texts/ingestion_jobs/document_chunks
migrations incl. ADR-004 lease columns on both job tables, pdfplumber +
python-docx parsers with canonical char-offset text, ADR-005 chunker),
**W3·B ingestion pipeline end-to-end** (shared lease-at-claim helper for both
job tables, OpenAI embeddings in the LLM client, ingestion worker handler with
terminal document-status flips, POST/GET ingestion HTTP surface with 409
re-run rules — now symmetric on extraction too, round-robin worker loop), and
**W3·C hybrid search + eval harness** (`GET /search` with pgvector +
full-text rankings fused by RRF-60 in the request path — the first
synchronous LLM surface, via a per-request client dep; hits carry citation
spans into parsed text; pure metric math + golden-record harness in
`evals/`);
ruff/mypy clean, 187 integration+unit tests green. Remaining W2 items: first
golden records (blocked on real documents), Anthropic SDK spike (blocked on a
real API key).

## Map

- `app/config.py` — Settings (.env): `database_url` (host port **5433**), `data_dir`,
  `max_upload_mb`, `log_level`, `openai_embedding_model` (W3·B)
- `app/db.py` — engine/sessionmaker lifecycle owned by lifespan; `get_session` dep
- `app/main.py` — `create_app()`; lifespan, mounts route routers, error handlers
- `app/middleware.py` — pure-ASGI request-ID middleware (echo/sanitize/generate,
  response header + access log)
- `app/request_context.py` — leaf module holding `request_id_ctx`; shared by
  middleware, logging filter, and services (audit correlation)
- `app/logging_config.py` — root logging + `RequestIdFilter` (`request_id=` on every line)
- `app/api/deps.py` — shared deps (`SessionDep`, `SettingsDep`, tenant `Header`,
  per-request `OpenAiClient` dep for the search surface)
- `app/api/routes/documents.py` — POST upload; GET list (`limit`/`offset` page
  envelope), GET by id, GET `/content` download, DELETE
- `app/api/routes/health.py` — `GET /healthz` probe
- `app/models/` — ORM: `Document`, `DocumentStatus`, `AuditLog` (append-only),
  `DocumentText` (parsed text + page map), `DocumentChunk` (embedding vector(1536)
  + generated tsvector), `IngestionJob` (lease columns per ADR-004 amendment)
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
  read-only-by-contract handlers — rules in `docs/llm-boundaries.md`),
  `embed()` (W3·B; re-sorts wire data by index so vectors align with inputs)
- `app/llm/cost.py` — pure token→USD math; pricing table locked by unit tests
- `app/services/extraction.py` — structured-outputs skeleton: `ObligationExtraction`
   schema + `extract_obligations()`; job lifecycle: `enqueue_extraction` (queued
   row only — no LLM in the request path), `get_extraction_job`,
   `run_next_extraction_job` (worker-side claim+run; every failure becomes a
   failed row); prompt-injection boundary in `docs/llm-boundaries.md`
- `app/services/parsing.py` — parsers: bytes → `ParsedDocument` (canonical
  "\n\n"-joined text, blocks with char offsets + kind, page map); DOCX via
  python-docx heading styles, PDF via pdfplumber + clause-number regex,
  plain text never yields headings (ADR-005); `UnsupportedParseError`
- `app/services/chunking.py` — ADR-005 chunker (pure logic): clause-primary,
  paragraph-seam fallback with 200-char overlap, whitespace-split last resort,
  fixed windows for unstructured text; `MAX_CHUNK_CHARS = 8000` constant;
  every chunk satisfies `text == parsed_text[char_start:char_end]`
- `app/models/extraction_job.py` + `app/repositories/extraction_jobs.py` —
  job rows; claim via `FOR UPDATE SKIP LOCKED` (ADR-004)
- `app/repositories/job_claims.py` — shared claim/lease mechanics for both
  job tables (ADR-004 amendment): eligible = queued or running with expired
  lease; claim sets a 15-min lease + increments `attempts`; past the cap
  (3) a row claims straight into `failed max_attempts_exceeded`
- `app/services/ingestion.py` — ingestion pipeline service: `enqueue_ingestion`
  (409 while queued/running per document; re-run from terminal state),
  `get_ingestion_job`, `run_next_ingestion_job` (worker handler: parse →
  chunk → embed → delete-then-insert document_texts/document_chunks; flips
  `Document.status` to `parsed`/`failed` on terminal states; every failure
  becomes a failed job row — parser exceptions are an open set, so the
  handler catches broadly)
- `app/repositories/ingestion_jobs.py`, `document_texts.py`,
  `document_chunks.py` — job rows + replace-style writes for re-runs
- `app/api/routes/ingestion.py` — `POST /documents/{id}/ingestion` → 202
  queued job; `GET /ingestion-jobs/{id}` polls status/result (tenant-scoped);
  409 detail `{"existing_job_id": ...}` shared with extraction
- `app/worker.py` — worker process (`python -m app.worker`): fails fast
  without an API key, round-robin claims across extraction + ingestion
  queues (rotation index per pass; a backlog in one queue can't starve the
  other), polls when idle
- `app/api/routes/extraction.py` — `POST /documents/{id}/extraction` → 202
  queued job; `GET /extraction-jobs/{id}` polls status/result (tenant-scoped)
- `app/services/search.py` — hybrid search (ADR-006): embeds the query in the
   request path, ranks chunks via pgvector cosine + Postgres FTS `ts_rank`,
   fuses both rankings with RRF (k=60 fixed; `rrf_fuse` is pure, unit-tested),
   returns `SearchHit`s whose char_start/char_end are citation spans into the
   document's parsed text; tenant-scoped, cross-document
- `app/api/routes/search.py` — `GET /search?q=&limit=` (limit default 10,
  cap 50); 503 unconfigured key / 502 failed query embed via the error table
- `evals/metrics.py` — pure metric math (recall@k, mechanical citation-span
   validity, extraction precision/recall on clause_ref+owner), unit-tested;
   `evals/harness.py` — golden-record CLI over `golden/<task>.jsonl`
   (`retrieve`, `extract_obligations`), JSON report with per-id scores
- `app/errors.py` — domain exception → 404/409/415/413/502/503 mapping,
  registered once (LlmError → 502/503 ready for future sync surfaces)
- `evals/` — golden-record placeholder; JSONL format decision in `evals/README.md`
- `docs/decisions/` — ADR-001 content-addressed storage; ADR-002 offset pagination;
  ADR-003 direct OpenAI SDK (no LLM framework); ADR-004 Postgres job rows
- `alembic.ini` + `migrations/` — async Alembic; `documents`, `audit_log`,
  `extraction_jobs`, `document_texts`, `document_chunks` (HNSW + GIN indexes),
  `ingestion_jobs`; pgvector extension; job-status enum types are dropped in
  downgrades (table drops alone leak them and break re-upgrade)
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

## Next (W3 — retrieval + evals; design settled, not yet implemented)

W3 item 1 (ingestion pipeline) was grilled to a fully settled design;
decisions below are confirmed, docs written (ADR-005, ADR-006, ADR-004
amendment, eval metric definitions, CONTEXT.md Chunk/Ingestion):

- Explicit `POST /documents/{id}/ingestion` → 202 + poll
  `GET /ingestion-jobs/{id}` (mirrors extraction; no auto-enqueue on upload —
  the future UI makes the calls, so the human experience is automatic while
  the API stays explicit).
- Parsing: pdfplumber (PDF) + python-docx (DOCX); parsed text + page map per
  document in `document_texts`; citation spans = char offsets into parsed
  text. Scanned PDFs/OCR out of scope.
- Chunking (ADR-005): clause-primary from parser structure; recursive
  paragraph-level fallback with overlap inside oversized clauses; fixed-size
  last resort. Chunker is pure logic → unit tests.
- Jobs: new `ingestion_jobs` table + shared claim/lease helper;
  lease-at-claim retry (ADR-004 amendment): stale `running` rows re-claimable
  after a 15-min lease, max 3 attempts → `failed max_attempts_exceeded`.
  Re-run rules: 409 while queued/running; re-run after terminal state
  replaces chunks/embeddings delete-then-insert. Symmetric for extraction.
- Embeddings: text-embedding-3-small (1536-d), HNSW index, pgvector via
  `pgvector/pgvector:pg17` compose image.
- Search (ADR-006): pgvector + Postgres FTS (tsvector + GIN) fused with RRF;
  `GET /search?q=` tenant-scoped, cross-document.
- `Document.status` flips to `parsed`/`failed` on terminal ingestion states
  (worker-side); the enum already declares these values.
- Worker: one process, round-robin claim across both job tables.
- Metrics defined in `evals/README.md` (citation validity, extraction
  accuracy, recall@k, task completion, latency/cost).

Implementation blocks:

- **W3·A** — DONE: migrations (pgvector extension, `document_texts`,
  `ingestion_jobs`, `document_chunks`) + parsers + chunker
- **W3·B** — DONE: ingestion worker handler (lease/retry, status flips) +
  embeddings + round-robin worker loop; plus the settled HTTP surface
  (`POST /documents/{id}/ingestion`, `GET /ingestion-jobs/{id}`) and the 409
  re-run rules, made symmetric on extraction
- **W3·C** — DONE: `GET /search` (RRF hybrid, first synchronous LLM surface
  via a per-request client dep) + citation spans on hits + eval harness for
  the mechanical metrics (recall@k, citation-span validity, extraction
  precision/recall)
- **W3·D** — first golden records when real documents land; verify gate

Still blocked (owner): real documents (golden records), live
`OPENAI_API_KEY` (first real call) and `ANTHROPIC_API_KEY` (SDK spike).

Open: auth deferred to multi-tenancy work; DELETE has no retention window yet;
audit_log retention/read APIs deferred until review-queue work; CI green
locally, first GitHub Actions run still unverified.
