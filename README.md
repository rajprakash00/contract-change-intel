# contract-change-intel

Work in progress. Upload an agreement plus its amendments and get back extracted
obligations (owners, deadlines, penalties), an explained diff between versions,
and impact mapping onto affected obligations — with citations, confidence scores,
and human review for low-confidence output.

Status: week 1 of an 8-week build. Backend foundations only (FastAPI, Postgres,
tests, CI); LLM features start in week 2.

## How it works

1. **Upload an Agreement** — the contract as first received.
2. **Upload an Amendment** — the next version of that Agreement.
3. **Extraction** — the system reads each version and lists its Obligations
   (who must do what by when, at what penalty) and Defined Terms, each with a
   Citation back to the source text.
4. **Change Report** — for every Amendment you get one report: what was added,
   modified, or removed, each Change explained and mapped to the Obligations
   it touches.
5. **Confidence + review** — every statement carries a Confidence score; anything
   below the threshold waits in a review queue for a human to approve or correct.

## Running locally

```sh
docker compose up -d
uv sync
uv run pytest
```

API server:

```sh
uv run uvicorn app.main:app --reload
```

Or fully containerized (API on :8000):

```sh
docker compose up -d --wait
docker compose run --rm app alembic upgrade head
```

## Configuration

Environment variables (see `.env.example`): `DATABASE_URL`, `DATA_DIR`,
`MAX_UPLOAD_MB`.

## Database schema

Schema changes go through Alembic (async engine, URL from app settings):

```sh
uv run alembic upgrade head                                  # apply
uv run alembic revision --autogenerate -m "describe change"  # new migration
```
