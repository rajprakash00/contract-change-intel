# contract-change-intel

Work in progress. Upload an agreement plus its amendments and get back extracted
obligations (owners, deadlines, penalties), an explained diff between versions,
and impact mapping onto affected obligations — with citations, confidence scores,
and human review for low-confidence output.

Status: week 1 of an 8-week build. Backend foundations only (FastAPI, Postgres,
tests, CI); LLM features start in week 2.

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

## Configuration

Environment variables (see `.env.example`): `DATABASE_URL`.
