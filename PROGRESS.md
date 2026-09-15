# Progress

Current state + next tasks only. AGENTS.md owns commands and constraints,
CONTEXT.md the language, `docs/decisions/` the ADRs, `docs/w4-decisions.md`
the settled W4 design, `docs/w5-decisions.md` the settled W5 design,
`docs/w6-decisions.md` the settled W6·A UI design, `docs/w6b-decisions.md`
the settled W6·B deploy design, `docs/writeup.md` the milestone writeup,
`infra/README.md` the deploy runbook. When a block lands, compress
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
through the running stack. · W6·B deploy scaffold (`infra/`,
docs/w6b-decisions.md, region **ap-south-1**): one flat Terraform stack —
VPC 2-AZ public-subnet Fargate / private-subnet RDS (no NAT), ALB + ACM +
Cloudflare DNS records (`/api/*` → API, rest → UI), RDS PG17 db.t4g.micro,
EFS access point at `/data` (POSIX 1000:1000; API image UID pinned to
match), ECR (api, ui), SSM SecureStrings (database_url, openai_api_key),
task execution role, four task definitions (api/ui/worker/migrate) with
desired counts 1/1/0 and `ignore_changes = [task_definition]` so CI owns
revisions; S3 backend with native lockfile. `web/Dockerfile` (Next
standalone, build-time NEXT_PUBLIC_* args) + `.dockerignore` +
`output: "standalone"`; both images build locally, the UI serves from the
container. CI: `deploy.yml` (dispatch-only) OIDC → ECR push → migration
run-task → service rollout; `ci.yml` image job builds both artifacts.
`infra/README.md` is the runbook; `docs/writeup.md` is the milestone
writeup with the baseline eval numbers and limitations. Deployed live
2026-09-11 at `https://change-report.byraj.dev` (full flow verified via
UI: login, upload, ingest, extract, amendment change report); first apply
hit ap-south-1 db.t4g.micro insufficient-capacity → db.t4g.small. ·
Post-deploy polish (issues #19–#21): font tokens fixed — body renders
Geist Sans (the token no longer self-references), duplicate
heading/serif tokens collapsed to one `--font-heading`, base type 17px;
custom SVG brand mark + favicon replace the stock assets and the dead
create-next-app SVGs are gone; a static landing page is the entry state
for logged-out visitors (no auto-redirect — both CTAs trigger the PKCE
redirect, signed-in users skip straight to the app); impact review items
carry the source Change in their payload (enriched at routing time,
`change` = kind/clause_ref/severity/description) and the queue renders
structured obligation + change fields with a deep-link to the change
report — legacy rows without the enrichment still render the obligation.
· Post-mvp (#22, #23): `GET /agreements/{id}/change-report-jobs` lists the
agreement's full Change Report history (tenant-scoped, 404 for unknown/
foreign agreements, newest first, every job with its status) and the
document detail page renders it for any signed-in principal —
queued/running rows show status, completed rows link into the report
view, light polling while unsettled; the delete-vs-amend race (an
amendment landing between the `has_amendments` pre-check and the delete)
now surfaces as the documented 409 through the central error table
instead of a raw 500 — the service converts the RESTRICT FK
IntegrityError to `DocumentHasAmendmentsError`. · Per-tenant rate
limiting (#24, ADR-010): the two LLM-enqueue POSTs spend a per-tenant
per-hour budget (settings knobs, `limits` library over in-process
MemoryStorage, one shared limiter per process) as a FastAPI dependency
resolved after the admin gate; exhausted budgets answer 429 with
Retry-After through the central error table, budgets are keyed
(kind, tenant) with the amount in the key, and the Redis-backed shared
storage is documented as the deliberate multi-replica scaling step
(ADR-010), not built. · LLM usage persistence + admin spend (#30): every
LLM call — extraction (citation-gate attempts counted one row per
attempt), ingestion embed batches, change reports (explanations, impact
recall, impact mappings), and the search request path (job_id NULL, kind
`search`) — persists one `llm_usage` row (model, tokens, cost, latency,
tenant/kind/job linkage, request_id, created_at; composite index
tenant_id+created_at). `LlmUsage` is produced where the call happens
(client `_log_usage` returns the record it logs; `LlmResult` carries
`latency_ms`, structured/embed calls return usage-carrying result
wrappers) and services persist it through `usage_service.sink(session,
tenant, kind, job)` — the sink is created by the job runners / the search
route, so the client layer stays DB-free. Reads are admin-only:
`GET /usage/spend[?group_by=job_type|job]` returns grouped rows plus the
tenant total; non-admin principals get 403. · Docs/meta (#26): the retired
second-provider spike is gone from the roadmap, progress notes, and
week-decision docs — ADR-003 keeps its one historical sentence (ADRs are
history); the README describes only behavior that exists (CI badge, live
demo link, auth/UI/deploy/eval sections in plain language) and an MIT
LICENSE landed. Stale-deferral cleanup: rate limits no longer listed as
deferred (landed via #24, ADR-010), and docs/writeup.md now matches
deployed reality — db.t4g.small (not micro), the delete-vs-amend race
surfaces as the documented 409 (#23), and the limitation line names
load tests, not rate limits, as the gap; infra/rds.tf header comment
fixed to match the actual instance class.

`OPENAI_API_KEY` live and verified end to end; the 6 CUAD fixtures are
ingested in the dev DB under the eval tenant.

Baselines (`evals/baselines/`): retrieve recall@5 0.82 / recall@10 0.96;
extract precision 0.90 / recall 1.0 / citation_validity 1.0; diff
precision 1.0 / recall 1.0; impact_map precision 0.83 / recall 0.75
(first live run, gpt-4o-mini — single-run wobble per the README caveat).
ruff/mypy clean; 374 integration+unit tests green.

## Open / blocked

- DELETE has no retention window; audit_log retention APIs still deferred
  (the tenant-scoped read API landed in W5·B, the `actor` column in W5·C).
- Auth0 provisioning complete: domain + API + claims Action attached to
  Login (verified 2026-09-07), SPA application registered for W6·A login
  (verified live against the prod domain), and per-user
  `app_metadata.role` assigned (one admin, one reviewer; verified
  2026-09-08, live SPA logins seen).
- ECR immutable repos: redeploying the *same* commit sha fails the image
  push (tag already exists) — redeploys must come from fresh commits;
  add a push guard to `deploy.yml` if same-sha reruns are ever wanted.

## Next

W6·B executed end to end: owner prerequisites → live deploy → full-flow
UI smoke against `https://change-report.byraj.dev` (done 2026-09-11;
runbook §First deploy now documents the counts-before-deploy step).
Remaining lifecycle: idle-at-zero or `terraform destroy` at the end of
the demo window. Deferred: load tests, retention, prod CUAD seeding (deliberately skipped — evals stay on the
local stack), same-sha deploy rerun guard.

## Gotchas

- Postgres job-status enum types are dropped explicitly in downgrades: table
  drops alone leak them and break re-upgrade.
- GitHub repos created on/after 2026-07-15 emit the **immutable OIDC sub
  claim** (`repo:<owner>@<owner-id>/<repo>@<repo-id>:ref:...`) — the trust
  policy must match that form, not the legacy name-only form; aud for
  configure-aws-credentials is `sts.amazonaws.com`, not the issuer URL.
- RDS db.t4g.micro repeatedly hit `insufficient-capacity` in ap-south-1
  (Mumbai); db.t4g.small provisions fine.
- Delete-vs-amend race: deleting a Document cascades its dependents in one
  transaction (ingestion/extraction jobs, Chunks, parsed text, the Change
  Reports naming it as the Amendment, and the Review Items routed from
  them); the base-with-amendments 409 stands, and an amendment landing in
  the race window between `has_amendments` and the delete surfaces as 409
  too — the service maps the RESTRICT FK IntegrityError onto
  `DocumentHasAmendmentsError` (#23).
- Auth0 SPA session restore on refresh needs refresh tokens, not the
  `prompt=none` iframe: browsers with partitioned third-party cookies
  block the iframe, which used to drop signed-in users back on the
  landing page. Wired `useRefreshTokens` + `cacheLocation: "localstorage"`
  + `offline_access` (providers.tsx); the Auth0 API must keep "Allow
  Offline Access" on.
- `get_settings` is lru_cached and auth tests flip `AUTH0_DOMAIN` via env —
  `tests/conftest.py::auth_env` clears the cache around every test; keep
  doing so if other env-driven settings grow knobs.
- The dev `cci` database accumulates rows across sessions (test residue on
  top of the eval fixtures); per-test `delete(Document)` cleanup then trips
  the document_chunks FK. CI and scratch DBs are clean and green — when the
  suite misbehaves locally, point `DATABASE_URL` at a scratch database
  first before suspecting the code.
