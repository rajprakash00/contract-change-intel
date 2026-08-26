# Progress

State: week 1 — W1·A done, W1·B read paths done (containerization pending), W1·C
started (request-ID middleware, size cap); ruff/mypy clean, 17 integration tests green.

## Map

- `app/config.py` — Settings (.env): `database_url` (host port **5433**), `data_dir`,
  `max_upload_mb`, `log_level`
- `app/db.py` — engine/sessionmaker lifecycle owned by lifespan; `get_session` dep
- `app/main.py` — `create_app()`; lifespan, mounts route routers, error handlers
- `app/middleware.py` — pure-ASGI request-ID middleware (echo/sanitize/generate,
  response header + access log); `request_id_ctx` for future trace correlation
- `app/api/deps.py` — shared deps (`SessionDep`, `SettingsDep`, tenant `Header`)
- `app/api/routes/documents.py` — POST upload; GET list (`limit`/`offset` page
  envelope), GET by id, GET `/content` download, DELETE
- `app/api/routes/health.py` — `GET /healthz` probe
- `app/models/` — ORM: `Document`, `DocumentStatus` (uploaded/parsed/failed)
- `app/schemas/` — Pydantic wire contracts (`DocumentRead`, `DocumentListPage`, conflict detail)
- `app/repositories/documents.py` — DB calls only: create, find_by_sha256, find_by_id,
  list_page, count_for_tenant, delete
- `app/services/documents.py` — upload/read/list/file-resolve/delete flows + domain
  exceptions (see PLAN Architecture)
- `app/storage/local.py` — content-addressed files `{data_dir}/{tenant_id}/{sha256}`;
  save/path/delete
- `app/errors.py` — domain exception → 415/413/409/404 mapping, registered once
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

Read/delete contract (all scoped by `X-Tenant-Id`; unknown id or other tenant's
row reads the same → 404 `{detail}`):
`GET /documents?limit=&offset=` → `{items[], total, limit, offset}`, newest first,
limit ≤ 100; `GET /documents/{id}` → `DocumentRead`;
`GET /documents/{id}/content` → stored bytes (`Content-Disposition` filename);
`DELETE /documents/{id}` → 204, removes row then file best-effort.
Every response carries `X-Request-ID` (echoed when sane, else generated).

## Next block (W1·C — hardening + gate)

1. Audit trail groundwork: append-only mutations table + request-id correlation.
2. Mime content sniffing on upload (stop trusting client-declared type).
3. Wire `request_id_ctx` into every log record via a logging filter.
4. Cursor pagination decision (offset is fine until lists grow; revisit with evals).
5. Close W1·B leftovers: multi-stage Dockerfile + compose `app` service + CI image-build job.
6. Backfill ADR-001 (content-addressed storage layout) into `docs/decisions/`; add an
   oversize-upload → 413 integration test (mapping exists, path untested).

Open: auth deferred to multi-tenancy work; DELETE has no retention window yet
(deferred to retention work); no GitHub Actions run verified yet.
