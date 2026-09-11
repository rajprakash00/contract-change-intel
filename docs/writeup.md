# Contract Change-Impact Intelligence — writeup

Milestone writeup (W5–W6, docs/w5-decisions.md "Milestone"). One page:
what the system does, how it is deployed, and the real eval numbers behind
the claims.

## What it does

Upload agreements and amendments; the system ingests them (parse →
structure-aware chunk → embed), extracts obligations with citations and
model-reported confidence, explains version diffs clause by clause, maps each
change onto affected obligations, and routes low-confidence output to a human
review queue instead of shipping it silently. Every mutating action lands in
an append-only audit log; identity is OIDC via Auth0 (multi-tenant, admin /
reviewer roles).

## Deployment (W6·B)

AWS **ap-south-1 (Mumbai)**: ECS Fargate (API, UI, worker — 0.25 vCPU / 512 MB
each), RDS PostgreSQL 17 (db.t4g.micro, pgvector) in private subnets, EFS for
content-addressed document bytes, ECR images, SSM SecureStrings for secrets.
Edge: purchased domain on Cloudflare (Universal SSL) → ALB with an ACM cert
(`Full (strict)`), path-routing `/api/*` → API, everything else → the Next.js
UI — same-origin, no CORS. Provisioned with one flat Terraform stack
(`infra/`); CI assumes an AWS role via OIDC, pushes sha-pinned images to ECR,
runs migrations as a one-off ECS run-task, and rolls the services. Lifecycle
is idle-at-zero: tasks run for demos and ingestion, the stack tears down
after the writeup window (decisions: `docs/w6b-decisions.md`).

## Eval numbers

Golden-record harness (`evals/`), model gpt-4o-mini, embeddings
text-embedding-3-small. Full methodology and per-record detail:
`evals/README.md`, `evals/baselines/`.

| Task | Metric | Score |
|---|---|---|
| retrieve | recall@5 | **0.82** |
| retrieve | recall@10 | **0.96** |
| extract_obligations | precision | **0.90** |
| extract_obligations | recall | **1.00** |
| extract_obligations | citation validity | **1.00** |
| diff | precision / recall | **1.00 / 1.00** |
| impact_map | precision | **0.83** |
| impact_map | recall | **0.75** |

Caveats, read before quoting:

- Single-run numbers on small golden sets (6 extraction records, 12 retrieval
  records, 2 diff / 2 impact records); they are baselines to regress against,
  not a benchmark.
- Diff and impact are per-record perfect-or-not; a set of 2 makes 1.0 easy
  and 0.75 mean one miss.
- Impact recall (0.75) is the known weakest task — candidate selection is
  citation-overlap based (`app/services/impact.py`); the misses in
  impact-001 are the case to inspect first.
- Task completion, latency, and cost metrics are defined but not yet
  mechanically graded/reported (evals/README.md).

## Limitations

- Postgres job-status enum types are dropped explicitly in downgrades;
  delete-vs-amend concurrency race is unhandled (falls through to a 500).
- No retention windows (uploads, audit log); DELETE is immediate.
- No rate limits or load-test numbers; demo posture, single instances,
  worker at desired count 0 while idle.
- Review dispositions are terminal (`pending → approved | edited | rejected`)
  — no re-entry loops, by design.
- Single-run LLM output wobbles between runs; confidence thresholds route
  below-threshold items to humans but do not calibrate the score itself.
