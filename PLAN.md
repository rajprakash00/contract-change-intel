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
