# Progress

State: week 1, day 1 complete — ruff/mypy clean, `/healthz` integration test green.

## Map

- `pyproject.toml` — deps + ruff/mypy/pytest config (source of truth)
- `app/config.py` — Settings reads `.env`; `database_url` default uses host port **5433**; `log_level`
- `app/db.py` — module-level engine/sessionmaker; `init_engine`, `dispose_engine`,
  `get_session` (FastAPI dep), `check_database` (raises on failure)
- `app/logging_config.py` — `configure_logging()` wired in lifespan; text format now,
  JSON at deploy milestone
- `app/main.py` — `create_app()`; lifespan owns engine init/dispose; `GET /healthz`
  returns `{status, database, version}`, 503 + warning log (with traceback) when DB down
- `tests/conftest.py` — client fixture; engine init/dispose manual (ASGITransport skips lifespan)
- `docker-compose.yml` — pgvector/pgvector:pg17, db `cci`, user/pass postgres, **5433→5432**
- `.github/workflows/ci.yml` — ruff, mypy, pytest; CI db on runner port 5432 via DATABASE_URL override

Constraints:

- Host port 5432 is occupied by an unrelated running stack — do not stop it; use 5433.
- Git staging/commits are handled by the owner, not tooling.

```sh
docker compose up -d --wait
uv run pytest
uv run uvicorn app.main:app --reload
```

## Next (day 2)

1. Alembic async setup + initial migration.
2. `documents` table: uuid pk, tenant_id (indexed), filename, mime_type, sha256,
   status enum (uploaded/parsed/failed), created_at/updated_at, unique (tenant_id, sha256).
3. Repository functions for inserts/lookups.
4. `POST /documents`: multipart upload → `./data/{tenant_id}/`; 415 on mime outside
   allow-list, 409 on duplicate sha256 within tenant.
5. Integration tests: happy path, duplicate, invalid mime.

Open: no GitHub remote yet (CI unverified); auth deferred to multi-tenancy work.
