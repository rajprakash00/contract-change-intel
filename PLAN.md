# Plan — Contract Change-Impact Intelligence

Upload an agreement plus its amendments. The system extracts obligations (owners,
deadlines, penalties, definitions), detects and explains changes between versions,
maps changed clauses onto affected obligations, shows citations + confidence, and
routes low-confidence output to a human review queue. Multi-tenant, audited.

## Stack

| Layer      | Choice |
|------------|--------|
| Language   | Python 3.13 (pinned via `.python-version`) |
| Package mgmt | uv (`pyproject.toml` + `uv.lock` committed; `.venv` never committed) |
| API        | FastAPI, Pydantic v2, pydantic-settings |
| DB         | PostgreSQL 17 via `pgvector/pgvector:pg17` image (extension present from day one) |
| ORM        | SQLAlchemy 2.x async + asyncpg |
| Tests      | pytest + pytest-asyncio, httpx ASGITransport against real Postgres |
| Lint/types | ruff (E,F,I,UP,B,SIM,ASYNC,RUF), mypy (disallow_untyped_defs, pragmatic strictness) |
| Workers    | Postgres-backed job table + worker process (no Celery) |
| Frontend   | Next.js/TypeScript (later phase) |
| Delivery   | Docker Compose locally, GitHub Actions CI, cloud deploy |

LLM provider: OpenAI primary (structured outputs + `text-embedding-3-small`);
Anthropic SDK once during week 2 for comparison. Frameworks (LangChain/LangGraph)
are not used for core pipelines; primitives first.

## Architecture

Code is layered strictly in one direction — each layer knows only the layers below it:

```text
api/routes ──▶ services ──▶ repositories ──▶ models
                 └──────▶ storage
schemas serve as the wire contracts at the router edge
errors.py maps domain exceptions onto HTTP once, app-wide
```

| Module       | Owns                        | Rules |
|--------------|-----------------------------|-------|
| `api/main.py` | router aggregation         | single `api_router` built via `include_router()`; the only thing `create_app()` mounts. |
| `api/deps.py` | shared dependencies        | `SessionDep` etc.; imported by route modules. |
| `api/routes/` | HTTP adapters              | parse request → call service → return schema. No business rules, no try/except, no logging. Handlers named for the verb+resource (`post_documents`). |
| `services/`  | business rules              | orchestrate repositories + storage; validation, dedupe, orchestration, audit logs. Raise domain exceptions carrying no HTTP semantics. No framework types cross this boundary (pass callables/data, not `UploadFile`). |
| `repositories/` | persistence             | DB calls only, one module per table, plain functions — no generic base classes. |
| `storage/`   | byte persistence            | filesystem today; swapping to object storage touches only this module. |
| `schemas/`   | Pydantic wire contracts     | response/request models; `from_attributes` to validate straight off ORM rows. |
| `models/`    | ORM rows                    | SQLAlchemy 2.0 `Mapped` style. |
| `errors.py`  | exception → HTTP mapping    | registered once in `create_app` via FastAPI exception handlers; new endpoints extend this table instead of adding per-route error handling. |
| `config.py`  | settings                    | env-driven; the only place that reads `.env`. |
| `db.py`      | engine/session lifecycle    | module-level singletons owned by the app lifespan. |

Blocking IO (disk writes) leaves the event loop via `asyncio.to_thread`.
Migrations are async Alembic with the URL taken from app settings so `DATABASE_URL`
overrides behave identically for API, tests, and migrations.

## Roadmap

- **W1 — Backend foundations**: FastAPI skeleton, settings, async engine, `/healthz`,
  Alembic migrations, `documents` upload endpoint, validation, integration tests, CI.
- **W2 — LLM reliability**: direct OpenAI calls, streaming, structured outputs, tool
  calling; retries/timeouts/rate-limit handling; token+cost logging; prompt-injection
  boundaries and safe tool design.
- **W3 — Retrieval + evaluations**: ingestion pipeline on the job-table worker;
  chunking, metadata, embeddings into pgvector, hybrid search (vector + full-text),
  citation spans. Golden datasets in `evals/`; metrics: citation validity, extraction
  accuracy, retrieval recall@k, task completion, latency, cost.
- **W4–W5 — Completion**: extraction schema, version diff + explanation, clause→
  obligation impact mapping, confidence scores, human-review queue, multi-tenancy +
  RBAC + audit trail, API rate limits, load-test numbers, deployed.
- **W6+ — Hardening**: dependency upgrades at milestones only (rerun tests + evals),
  performance pass, final technical writeup.

## Engineering policy

- Prefer direct primitives over abstractions; introduce a library only where it
  demonstrably reduces complexity.
- Repository functions only for tables with non-trivial queries; no generic base classes.
- Integration tests by default; unit tests only for pure logic (chunking, diffing, cost
  math). Do not mock the database or ORM.
- Background jobs are rows in Postgres with idempotent handlers, not fire-and-forget tasks.
- Persist structured traces only (request ID, redacted inputs/outputs, latency, token
  usage, cost, retries); never persist model chain-of-thought.
- PII: minimize stored fields, redact before persistence, define retention rules
  (regex alone is not sufficient).
- Documentation maintained continuously: ADRs in `docs/decisions/` (~6–8, written when
  the decision is made, including rejected alternative), limitations section in README,
  `NOTES.md` bug-investigation log, one-page `docs/writeup.md` with real eval numbers.
