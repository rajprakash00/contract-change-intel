# Progress

State: week 1, day 2 complete — Alembic migrations + `documents` table +
`POST /documents` upload; ruff/mypy clean, 6 integration tests green.

## Map

- `app/config.py` — Settings (.env): `database_url` (host port **5433**), `data_dir`,
  `max_upload_mb`, `log_level`
- `app/db.py` — engine/sessionmaker lifecycle owned by lifespan; `get_session` dep
- `app/main.py` — `create_app()`; lifespan, mounts `api_router`, error handlers
- `app/api/main.py` — aggregates route routers into one `api_router`
- `app/api/deps.py` — shared deps (`SessionDep`, `SettingsDep`)
- `app/api/routes/documents.py` — thin adapter for `POST /documents`
- `app/api/routes/health.py` — `GET /healthz` probe
- `app/models/` — ORM: `Document`, `DocumentStatus` (uploaded/parsed/failed)
- `app/schemas/` — Pydantic wire contracts (`DocumentRead`, conflict detail)
- `app/repositories/documents.py` — DB calls only: create, find_by_sha256
- `app/services/documents.py` — upload flow + domain exceptions (see PLAN Architecture)
- `app/storage/local.py` — content-addressed files `{data_dir}/{tenant_id}/{sha256}`
- `app/errors.py` — domain exception → 415/413/409 mapping, registered once
- `alembic.ini` + `migrations/` — async Alembic; initial migration creates `documents`
- `tests/conftest.py` — applies migrations per session; per-test DATA_DIR tmp dir
- `docker-compose.yml` — pgvector/pgvector:pg17, **5433→5432**
- `.github/workflows/ci.yml` — ruff, mypy, pytest against real Postgres

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
(`{existing_id}`), 413 over size cap, 415 mime outside allow-list, 422 missing header.

## Next (day 3)

1. `GET /documents` list + `GET /documents/{id}` per tenant; download of stored bytes.
2. DELETE semantics (row + file) or defer to retention work.
3. Request-ID middleware groundwork.
4. Consistent error body format across endpoints.

Open: no GitHub remote yet (CI unverified); auth deferred to multi-tenancy work;
client-declared mime trusted until content sniffing lands with the parser.
