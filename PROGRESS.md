# Progress

Current state + next tasks only. AGENTS.md owns commands and constraints,
CONTEXT.md the language, `docs/decisions/` the ADRs, `docs/w4-decisions.md`
the settled W4 design, `docs/w5-decisions.md` the settled W5 design,
`docs/w6-decisions.md` the settled W6·A UI design. When a block lands, compress
it to a line here — the file's history lives in git, not in this file.

## State

Done through **W5·C OIDC auth**: W1 foundations / read paths /
hardening gate · W2 LLM client + extraction job surface · W3 ingestion
pipeline (parse → chunk → embed), RRF hybrid search, golden records + eval
harness · W4·A parse-gated extraction (409 until ingestion completes), worker
reads parsed text from `document_texts`, citation gate with one retry that
drops uncited items on the final attempt, `Citation` / clamped `Confidence`
(ADR-007) / `DefinedTerm` schema · W4·B `documents.amends_document_id`
self-FK (RESTRICT; parent deletes 409 while amendments exist) +
`amends_document_id` form field on `POST /documents`, tenant-scoped parent
validation (404 unknown/foreign parent; duplicate bytes still 409) · W4·C
clause-level alignment + pure diff (`app/services/diffing.py`; sections from
parsed-text paragraphs — the chunker's fixed-window fallback would degenerate
plain-text alignment — number normalization "8.02"≡"8.2", tuple keys guard
"8.2" vs "8.2.1"), `change_report_jobs` (third ADR-004 sibling),
`POST /agreements/{id}/change-report` naming the amendment (404 unknown/
foreign, 409 unlinked amendment, 409 naming the first missing
ingestion/extraction job), `GET /change-report-jobs/{id}`, one structured
explanation call per version pair (per-Change description + severity),
`diff` golden task (mechanical precision/recall; no LLM, no DB) · W4·D
document-scoped search variant (`search_document`; repo rankers take an
optional `document_id` filter — `GET /search` stays tenant-wide), per-Change
impact mapping in the change report worker: changed wording recalls base
chunks, citation-overlap candidate selection (`app/services/impact.py`,
pure + unit-tested), one structured mapping call per Change → affected
Obligations with per-Impact Confidence (ADR-007); report rows gain
`impacts` per Change; impact grading eval deferred to W5. · W5·A review
queue (docs/w5-decisions.md): `review_items` with a flat state machine
`pending → approved | edited | rejected` — resolutions are terminal (409 on
re-resolve) and `edited` captures corrected values; the extraction and
impact-mapping workers route items whose confidence falls strictly below
the per-kind threshold from settings
(`review_confidence_threshold_extraction` / `_impact`); reviewer API is
`GET /review-items[?status=]`, `GET /review-items/{id}`,
`POST /review-items/{id}/resolution` (Disposition; audited as
`review.resolve`). Routing is additive — job results ship regardless. ·
W5·B audit trail read + impact-grading eval: the six mutating services
already write append-only `audit_log` rows (actor=tenant, request_id,
action, resource target, detail); the read surface is
`GET /audit-log[?action=][&limit=]` — tenant-scoped, chronological,
limit truncates from the newest end (W5·B in docs/w5-decisions.md) —
and the deferred W4·D impact eval landed as the `impact_map` golden
task (one real mapping call per detected Change against the record's
obligations as candidates; per-Change precision/recall matched on
(clause_ref, owner) via `evals.metrics.impact_precision_recall`). · W5·C
OIDC auth via Auth0 (ADR-008): bearer JWTs verified against Auth0's JWKS
(RS256, issuer/audience/expiry-strict, in-process key cache with TTL + one
refresh on unknown kid); claims map to Tenant + Role
(`https://cci/tenant_id`, `https://cci/role` ∈ admin/reviewer) — the
`X-Tenant-Id` header is gone, tenant and actor come only from the token;
document/job mutations are admin-only, review dispositions
reviewer-or-admin, reads any authenticated principal; `audit_log.actor`
column landed (token subject; NULL for pre-auth rows); no "auth off" mode
— unconfigured auth is 503, `/healthz` stays open; tests fake the JWKS
wire at the transport seam (`tests/fake_jwks.py`, same precedent as
`tests/fake_openai.py`) with RSA-signed test tokens. Live smoke verified
against real Auth0 (tenant `change-report.us.auth0.com`, audience
`https://change-report.us.auth0.com/me/`): no-token 401 with Bearer
challenge, claim-scoped reads, admin upload 201, and the audit row's
`actor` equal to the token subject. Token minting for smoke tests:
`auth0 test login --audience <API identifier>` (the CLI's default
audience is the Management API — always pin yours). · W6·A thin Next.js UI
(`web/`, docs/w6-decisions.md): Auth0 SPA login via `@auth0/auth0-react`
(PKCE, `/callback`, bearer attached per request), same-origin `/api/...`
everywhere — dev proxy is a Next rewrite (`/api/:path*` → API, prefix
stripped), prod is ALB path-routing, and the API prefix lives in exactly
one place (`Settings.root_path` → FastAPI `root_path`, empty in dev).
shadcn/ui + Tailwind with a "calm legal-tech" token layer (serif display
headings, ink-blue accent). Surfaces: documents table + upload (file +
amends parent select; upload/delete admin-only, gated client-side off the
decoded `https://cci/role` claim), document detail with ingestion/extraction
enqueue + job polling (5s while queued/running, stops when settled),
change-report view (kind/severity/description per Change, per-Impact
obligations with Confidence), review-queue triage (status filter,
approve/reject, edit via corrected-values JSON dialog). react-query for
server state, react-table v8 for the two tables, RHF+zod for the upload
form, sonner toasts. Pure-logic unit tests (vitest): role-claim mapping and
the job-settled/poll predicate; npm lint/tsc/build green; proxy verified
through the running stack.

`OPENAI_API_KEY` live and verified end to end; the 6 CUAD fixtures are
ingested in the dev DB under the eval tenant.

Baselines (`evals/baselines/`): retrieve recall@5 0.82 / recall@10 0.96;
extract precision 0.90 / recall 1.0 / citation_validity 1.0; diff
precision 1.0 / recall 1.0; impact_map precision 0.83 / recall 0.75
(first live run, gpt-4o-mini — single-run wobble per the README caveat).
ruff/mypy clean; 345 integration+unit tests green.

## Open / blocked

- `ANTHROPIC_API_KEY` (owner) — blocks the Anthropic SDK spike.
- First GitHub Actions run unverified (CI is green locally).
- DELETE has no retention window; audit_log retention APIs still deferred
  (the tenant-scoped read API landed in W5·B, the `actor` column in W5·C).
- Auth0 provisioning is live for one admin user (domain + API + claims
  Action attached to Login, verified 2026-09-07). Remaining owner tasks
  before the W6 deploy: role assignment per user (`app_metadata.role` in
  Auth0), and the SPA application registration for W6·A login (allowed
  callback/logout URLs + web origins `http://localhost:3000` — callback route
  `/callback` per SDK convention — prod values added when the W6·B domain
  exists).

## Next

The next work is **W6·B AWS ECS/RDS deploy via Terraform** → deployed
API + UI + writeup with eval numbers. UI-side owner prerequisite for a
real login: the Auth0 SPA application registration (allowed callback/
logout URLs + web origins `http://localhost:3000`, callback route
`/callback`). Deferred: rate limits, load tests, Anthropic spike,
retention.

## Gotchas

- Postgres job-status enum types are dropped explicitly in downgrades: table
  drops alone leak them and break re-upgrade.
- Delete-vs-amend race: an amendment inserted between `has_amendments` and
  the delete falls through to the RESTRICT FK and surfaces as a 500; to be
  handled if concurrent-write tests arrive.
- `get_settings` is lru_cached and auth tests flip `AUTH0_DOMAIN` via env —
  `tests/conftest.py::auth_env` clears the cache around every test; keep
  doing so if other env-driven settings grow knobs.
