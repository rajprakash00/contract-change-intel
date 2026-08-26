# AGENTS.md

Guidance for AI coding agents in this repo.

## Project

Contract Change-Impact Intelligence: upload agreements + amendments, extract obligations,
explain version diffs, map impact onto affected clauses, route low-confidence output to
human review. Multi-tenant, audited.

- `PLAN.md` — full architecture rationale, roadmap, engineering policy. **Read only for
  non-trivial/architecture-level work or roadmap questions**; small scoped edits don't need it.
- `PROGRESS.md` — current state + next tasks; keep it updated when a task lands.

## Stack

Python 3.13 · uv · FastAPI + Pydantic v2 · PostgreSQL 17/pgvector via SQLAlchemy 2 async +
asyncpg · async Alembic · pytest + httpx ASGITransport against real Postgres.
Integration tests by default; unit tests only for pure logic (chunking, diffing, cost math).
Never mock the database or ORM.

## Commands

```sh
docker compose up -d --wait        # Postgres, host port 5433 (see Constraints)
uv run ruff check . && uv run ruff format --check .   # CI parity
uv run mypy app migrations/env.py                      # CI parity
uv run pytest                      # conftest applies migrations automatically
uv run uvicorn app.main:app --reload
```

Run lint + typecheck + tests before declaring any backend change done.
CI (`.github/workflows/ci.yml`) runs exactly these; the `verify` skill wraps the same loop.

## Architecture — strict one-directional layering

`api/routes → services → repositories → models`; services may also call `storage`.
`schemas` are wire contracts at the route edge; `errors.py` maps domain exceptions → HTTP once, app-wide.

| Layer | Rules |
|---|---|
| `app/api/main.py` | Aggregates all routers into one `api_router` via `include_router`; included by `create_app()`. |
| `app/api/deps.py` | Shared FastAPI dependencies (`SessionDep`, `SettingsDep`). |
| `app/api/routes/` | Parse request → call service → return schema. No business rules, no try/except (probe endpoints excepted), no logging. One module per resource; handlers named verb+resource (`post_documents`). |
| `app/services/`  | Business rules. Raise domain exceptions carrying no HTTP semantics. No framework types cross this boundary (pass `file.read`, not `UploadFile`). Blocking IO via `asyncio.to_thread`. |
| `app/repositories/` | DB calls only, plain functions, one module per table, no generic base classes. |
| `app/storage/`   | Byte persistence only; content-addressed `{data_dir}/{tenant_id}/{sha256}`. |
| `app/models/`    | SQLAlchemy 2.0 `Mapped` style. |
| `app/schemas/`   | Pydantic v2; `from_attributes` to validate straight off ORM rows. |

New failure mode ⇒ domain exception in the service + handler registered in `errors.py`.
Never per-route try/except. New table ⇒ new migration via Alembic autogenerate.

## Conventions

- Settings only via `app/config.py` (reads `.env`); nothing else touches env/files directly.
- Logging: stdlib, key=value style (`tenant=%s document=%s sha=%s`).
- Primitives over abstractions: add a dependency only if it demonstrably reduces complexity.
- Persist structured traces only (request ID, redacted I/O, latency, token usage, cost); never model chain-of-thought. Minimize/redact PII.

## Constraints

- Host port **5432 belongs to an unrelated running stack** — do not stop/reconfigure it;
  local Postgres maps 5433→5432 in docker-compose.
- Git staging/commits are handled by the owner. Do not commit unless explicitly asked.
