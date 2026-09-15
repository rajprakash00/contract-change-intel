# W6·B AWS deploy: settled decisions

Settled in the W6·B grill session (2026-09-10). Scope from docs/w5-decisions.md
("Deploy (W6·B)"): deployed API + UI provisioned with Terraform, with live eval
numbers in docs/writeup.md. Fly.io remains the named fallback if VPC/IAM
provisioning overruns.

## Topology

1. **AWS ECS Fargate + RDS PostgreSQL 17 + ECR, ap-south-1 (Mumbai), Terraform
   throughout.** (Region pinned by the owner at implementation time; the grill
   session had used us-east-1 as a placeholder.) One flat `infra/` stack
   (no remote backend plumbing, no module nesting).
2. **Edge: purchased domain + Cloudflare free zone → ALB → ECS services.**
   Cloudflare is DNS and TLS termination (Universal SSL, `Full (strict)` against
   an ACM cert on the ALB). The ALB stays the path router: `/api/*` → API
   service (`root_path=/api`, docs/w6-decisions.md #6 unchanged), everything
   else → UI service. Same-origin serving survives unchanged. The ALB remains
   publicly reachable (demo posture; an SG locked to Cloudflare's published
   ranges is optional polish, not a goal).
3. **Network: 2 AZs; Fargate tasks in public subnets, RDS in private subnets,
   no NAT gateway.** Tasks get public IPs and egress via the internet gateway;
   RDS needs no public IP. Avoids the ~$32/mo NAT standing cost. Security-group
   chain: ALB → task SGs → RDS 5432.
4. **Compute: three Fargate services, 0.25 vCPU / 512 MB each.** API
   (uvicorn), UI (web Dockerfile, Next.js standalone), worker
   (`python -m app.worker`, same image, command override). Desired counts:
   API 1, UI 1, **worker 0** — scaled to 1 only for ingestion/demo runs; the
   FOR UPDATE SKIP LOCKED claim design (ADR-004) already makes >1 safe.

## Storage, database, secrets

5. **Document bytes: EFS mounted at `data_dir` on API and worker tasks**
   (ADR-009). The content-addressed layout is unchanged; Fargate's ephemeral
   disk would lose uploads on task replacement.
6. **RDS PostgreSQL 17, db.t4g.micro, 20 GB gp3, single-AZ.** pgvector needs no
   extra work: the W3 migration already runs `CREATE EXTENSION IF NOT EXISTS
   vector`, and RDS PG17 ships pgvector 0.8.2 (verified against the local
   `pgvector/pgvector:pg17` image).
7. **Secrets: SSM Parameter Store SecureStrings.** DB master password and
   `OPENAI_API_KEY` reach tasks via the task-definition `secrets` block; plain
   env vars only for non-secrets (`AUTH0_DOMAIN`, `AUTH0_AUDIENCE`,
   `root_path`). Consistent with app/config.py's env-only posture.

## Delivery

8. **Migrations: one-off ECS run-task from CI** (`alembic upgrade head`)
   before rolling new task revisions. "Migrations are not automatic" stays
   true in prod; no racing tasks each running migrations.
9. **CI: GitHub Actions assumes an AWS role via OIDC** (no long-lived keys in
   repo secrets) → build/push API + UI images to ECR → migration run-task →
   `update-service` rollout. Matches docs/w5-decisions.md ("CI builds and
   pushes the image").
10. **Terraform state: S3 backend with native lockfile** (`use_lockfile`,
    Terraform ≥1.10 — no DynamoDB lock table), versioning on, bucket created
    once outside Terraform and deliberately surviving teardown. State
    outliving the stack is what makes the destroy → redeploy cycle safe.
11. **Lifecycle: idle-at-zero.** Tasks run only when needed (0 desired while
    idle; scaled up for demos, ingestion, and live smoke). After the writeup
    ships, the stack is torn down. Redeploying is fully scripted:
    `terraform apply` + CI push + migration task + fixture re-seed
    (`evals/seed_fixtures.py`) — under an hour, mostly waiting.

## Out of scope / fallback

- Load tests, retention stay deferred (PROGRESS.md).
- Fly.io fallback unchanged: engaged only if VPC/IAM provisioning overruns;
  same images, different scaffold.
- RDS stop is not used as a cost lever (auto-resumes after 7 days); teardown
  is the off switch.
