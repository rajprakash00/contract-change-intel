# W5 → demo deployment: settled decisions

Settled in the W5 grill session. Slice order: **W5·A review queue → W5·B
audit trail + impact-grading eval → W5·C OIDC auth**, then **W6·A thin UI →
W6·B AWS deploy**. Load tests, retention windows are deferred hardening.

## Milestone (the target)

Deployed API + thin UI + review queue + OIDC auth + `docs/writeup.md` with
real eval numbers. Everything else is a post-milestone addendum.

## Review queue state machine (W5·A)

Flat: `pending → approved | edited | rejected`. `edited` captures corrected
values before resolution; no re-entry loops. Workers (extraction, impact
mapping) create Review Items when Confidence falls below the threshold;
threshold per job kind from settings. Reviewer acts via API; the resolution
is a **Disposition** (approved / edited / rejected). Routing is additive:
a job's own result ships regardless; the queue never gates it.

## Impact-grading eval (W5·B)

The eval deferred from W4·D lands here — mechanical grading of impact
mappings. It completes the eval story the writeup reports.

## Audit trail (W5·B)

Append-only `audit_log` (actor, tenant, action, target, timestamp,
request_id); services write on mutating actions; tenant-scoped read API.
No retention window yet (matches the existing OPEN item).

## Authentication (W5·C)

OIDC via Auth0: real user accounts without self-built identity boilerplate.
FastAPI verifies bearer JWTs against Auth0's JWKS; tests fake JWKS at the
transport seam (same precedent as `tests/fake_openai.py`). Claims map to
Tenant + Role. ADR lands with this block. Open at block design: role names
(admin/reviewer), tenant creation flow (Auth0 org per Tenant).

## UI (W6·A)

Next.js/TS sibling directory in-repo. Thin cut: upload + document list,
change-report view with Citations/Confidence, review-queue triage. Auth via
Auth0 SPA login → bearer token to the API.

## Deploy (W6·B)

AWS ECS Fargate + RDS PostgreSQL (pgvector is supported on RDS) + ECR,
provisioned with Terraform; CI builds and pushes the image. Chosen over a
VPS + compose for IaC and managed Postgres; teardown after demoing keeps
cost near zero. Fallback if the VPC/IAM yak-shaving overruns: Fly.io.

## Writeup (milestone)

`docs/writeup.md` one-pager with real eval numbers + README limitations
section.
