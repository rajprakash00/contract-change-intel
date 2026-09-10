# Web UI (W6·A)

Thin Next.js client for the contract-change-intel API. Design decisions live
in `docs/w6-decisions.md` (repo root).

## Run

```sh
cp .env.example .env.local   # fill in the Auth0 SPA values
npm install
npm run dev                  # http://localhost:3000, proxies /api/* to the API
```

The API runs separately from the repo root (`uv run uvicorn app.main:app
--reload`); in dev the browser only ever talks to `localhost:3000/api/...`
and the Next rewrite forwards to the API with the prefix stripped. In prod
the ALB path-routes `/api/*` instead — there is no CORS anywhere.

## Layout

- `src/lib/api.ts` — the API surface (types mirrored from `app/schemas`),
  bearer attached per request from the Auth0 SDK.
- `src/lib/roles.ts` — role read from the decoded `https://cci/role` claim;
  UI gating is presentational only, the API remains the enforcement point.
- `src/lib/jobs.ts` — the light-polling predicate (5s while queued/running).
- `src/app/` — documents list + upload, document detail (pipeline jobs,
  change-report trigger), change-report view, review-queue triage.

## Checks

```sh
npm test          # vitest — pure logic (role mapping, polling predicate)
npm run lint
npx tsc --noEmit
npm run build     # produces .next/standalone for web/Dockerfile (W6·B)
```
