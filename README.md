# contract-change-intel

[![ci](https://github.com/rajprakash00/contract-change-intel/actions/workflows/ci.yml/badge.svg)](https://github.com/rajprakash00/contract-change-intel/actions/workflows/ci.yml)
[![deploy](https://github.com/rajprakash00/contract-change-intel/actions/workflows/deploy.yml/badge.svg)](https://github.com/rajprakash00/contract-change-intel/actions/workflows/deploy.yml)

Upload an agreement plus its amendments. Get back extracted obligations
(owners, deadlines, penalties), an explained diff between versions, and
impact mapping onto affected obligations — with citations, confidence
scores, and human review for low-confidence output.

**Live demo:** <https://change-report.byraj.dev> — log in with the demo
credentials below.

## How it works

1. **Upload an agreement** — the contract as first received.
2. **Upload an amendment** — the next version of that agreement.
3. **Extraction** — the system reads each version and lists its obligations
   (who must do what by when, at what penalty) and defined terms. Every
   statement cites the source text.
4. **Change report** — each amendment gets one report: what was added,
   modified, or removed. Each change is explained and mapped to the
   obligations it touches.
5. **Review** — every statement carries a confidence score. Anything below
   the threshold waits in a review queue for a human to approve or correct.

## Try the demo

Two provisioned demo accounts, ready to use:

| Account | Email | Password | Can do |
|---|---|---|---|
| Admin | `demo-admin@byraj.dev` | `78KeoOwmxw0HrY4fsLITpkR` | Everything: upload, delete, enqueue jobs, dispositions |
| Reviewer | `demo-reviewer@byraj.dev` | `47EO4c9K13BTq8O5K4tY3W` | Read + resolve review items only |

Suggested first run: upload an agreement, then an amendment for it, then
generate the change report for the pair.

Log in with Auth0 to use the app. Uploads and deletes need the admin role.
Review dispositions need admin or reviewer. Every mutating action lands in
an audit log. Enqueuing LLM work spends a per-tenant hourly budget — the
demo tenant runs a reduced one (5 extractions / 2 change reports per hour);
an exhausted budget answers 429 with a retry-after hint.

## Run it locally

Backend:

```sh
docker compose up -d --wait
uv sync
uv run alembic upgrade head
uv run pytest
uv run uvicorn app.main:app --reload
```

UI (separate terminal; it proxies `/api/*` to the API):

```sh
cd web
cp .env.example .env.local   # fill in the Auth0 SPA values
npm install
npm run dev                  # http://localhost:3000
```

## Configuration

Environment variables (see `.env.example`): `DATABASE_URL`, `DATA_DIR`,
`MAX_UPLOAD_MB`, and the auth pair `AUTH0_DOMAIN` + `AUTH0_AUDIENCE`.
Bearer JWTs via Auth0 are mandatory — with auth unconfigured the API
answers 503, it does not run open.

## Deploy

Terraform in `infra/` provisions AWS ECS Fargate, RDS PostgreSQL 17
(pgvector), EFS, and the ALB edge. `infra/README.md` is the runbook.
CI builds the images and runs migrations as a one-off task;
`scripts/demo-up.sh` / `scripts/demo-down.sh` open and close the demo
window (ADR-012).

## Evaluation

Golden-record harness (`evals/`), model gpt-4o-mini, embeddings
text-embedding-3-small. Methodology: `evals/README.md`; per-record
detail: `evals/baselines/`.

| Task | Metric | Score |
|---|---|---|
| retrieve | recall@5 | 0.82 |
| retrieve | recall@10 | 0.96 |
| extract | precision / recall | 0.90 / 1.00 |
| extract | citation validity | 1.00 |
| diff | precision / recall | 1.00 / 1.00 |
| impact_map | precision / recall | 0.83 / 0.75 |

These are single-run numbers on small golden sets. Read them as baselines
to regress against, not a benchmark. Full caveats: `docs/writeup.md`.

## License

[MIT](LICENSE)
