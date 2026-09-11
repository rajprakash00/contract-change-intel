# W6·B deploy runbook

One flat Terraform stack, region **ap-south-1** (Mumbai). Decisions:
`docs/w6b-decisions.md`. First deploy is mostly owner prerequisites; after
that, redeploy is scripted (under an hour, mostly waiting).

## Stack layout

| File | Contents |
|---|---|
| `network.tf` | VPC, 2 AZs, public + private subnets, IGW (no NAT — decision #3) |
| `security.tf` | SG chain ALB → api/ui task SGs → RDS 5432, EFS 2049 |
| `alb.tf` | ALB, ACM cert, `/api/*` → API, rest → UI; Cloudflare records |
| `efs.tf` | EFS + access point (`/data`, POSIX 1000:1000 — ADR-009) |
| `rds.tf` | RDS PG17 db.t4g.small, 20 GB gp3, single-AZ (decision #6; small because micro hits insufficient-capacity in ap-south-1) |
| `ecr.tf` | Two immutable ECR repos (api, ui) |
| `ssm.tf` | SecureStrings: `database_url`, `openai_api_key` (decision #7) |
| `iam.tf` | Task execution role (+ SSM/KMS read) |
| `ecs.tf` | Cluster, api/ui/worker/migrate task defs + services |
| `backend.tf` | S3 state backend with native lockfile (decision #10) |

## One-time owner prerequisites

1. **S3 state bucket** (outside Terraform; survives teardown):
   ```sh
   aws s3api create-bucket --bucket cci-tfstate-ap-south-1 \
     --region ap-south-1 \
     --create-bucket-configuration LocationConstraint=ap-south-1
   aws s3api put-bucket-versioning --bucket cci-tfstate-ap-south-1 \
     --versioning-configuration Status=Enabled
   ```
2. **Cloudflare free zone** for the purchased domain; a scoped API token
   (Zone → DNS Edit + SSL Edit). Terraform creates the ACM validation
   records and the proxied CNAME → ALB; the zone itself stays manual.
3. **AWS OIDC role for CI**: an IAM role trusting
   `token.actions.githubusercontent.com` (repo `rajprakash00/contract-change-intel`),
   with permissions over ECS/ECR/SSM/ACM/IAM-pass-role and state bucket read.
   Record its ARN as the repo **variable** `AWS_DEPLOY_ROLE_ARN`.
4. **Repo variables** (non-secrets, inlined into the UI bundle at build time):
   `NEXT_PUBLIC_AUTH0_DOMAIN`, `NEXT_PUBLIC_AUTH0_CLIENT_ID`,
   `NEXT_PUBLIC_AUTH0_AUDIENCE` (same values as `web/.env.example`).

## First deploy

```sh
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in domain, zone id, auth0
terraform init
# First apply with everything idle: no image exists in ECR yet (IMMUTABLE
# tags), so services started now would crash-loop until CI pushes one.
terraform apply -var=api_desired_count=0 -var=ui_desired_count=0
```

Then:

5. **OpenAI key**: overwrite the placeholder SecureString:
   ```sh
   aws ssm put-parameter --name /cci/prod/openai_api_key \
     --type SecureString --value sk-... --overwrite
   ```
6. **Auth0 SPA application**: add the prod callback
   `https://<domain>/callback` and logout/web-origin `https://<domain>`
   (the remaining item in PROGRESS.md's Open section).
7. **Deploy**: `gh workflow run deploy` — pushes both images (sha tags),
   runs the migration run-task (`alembic upgrade head`), rolls all services,
   and waits for stability.
8. **Seed + demo**: scale the worker to 1, re-seed the CUAD fixtures, ingest:
   ```sh
   aws ecs update-service --cluster cci-prod --service cci-prod-worker \
     --task-definition cci-prod-worker --desired-count 1
   python evals/seed_fixtures.py   # against the deployed API
   ```
   Scale back: same command with `--desired-count 0`.

## Redeploy

`terraform apply` (if vars changed) → `gh workflow run deploy` → fixture
re-seed if the DB was torn down.

## Idle / teardown (decision #11)

```sh
terraform apply -var=api_desired_count=0 -var=ui_desired_count=0 \
  -var=worker_desired_count=0   # idle at zero; tasks bill nothing
terraform destroy               # end of demo window
```

The S3 state bucket deliberately survives; redeploy starts from real state.

## State notes

- `database_url` (containing the DB master password) lives in an SSM
  SecureString whose value Terraform composes — it is therefore present in
  the Terraform state. Inherent to decision #7's SSM-created-by-Terraform
  design; the state bucket is versioned and access-controlled, and the DB
  dies with the stack at teardown.
- The stack name prefix (`cci/prod`) is the single source for ECR repo
  names; CI reads the repo URLs from Terraform outputs rather than
  re-deriving them, so renaming `project`/`environment` cannot silently
  push to nonexistent repos.

## Region note

The grill session settled on us-east-1; the owner pinned **ap-south-1**
(Mumbai) instead — everything in this stack and CI is already ap-south-1
(`docs/w6b-decisions.md` #1 records the region as ap-south-1 now).
