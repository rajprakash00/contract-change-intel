# Testing & observability runbook

Per-session checklist for exercising every flow, where the logs live, and what
to track. Born from the two demo incidents that both reduced to "nobody was
watching": the worker scaled to 0 while jobs queued, and the placeholder
OpenAI key in SSM.

## Pre-flight (before touching the app)

```sh
# 1. Worker running — desired=1/running=1 (scale up if 0; scale back to 0 after)
aws ecs describe-services --cluster cci-prod \
  --services cci-prod-api cci-prod-worker cci-prod-ui \
  --output json | python3 -c "import json,sys; [print(s['serviceName'],'desired=',s['desiredCount'],'running=',s['runningCount']) for s in json.load(sys.stdin)['services']]"
aws ecs update-service --cluster cci-prod --service cci-prod-worker \
  --task-definition cci-prod-worker --desired-count 1   # when 0

# 2. OpenAI key is not the placeholder (prints a verdict, never the key)
aws ssm get-parameter --name /cci/prod/openai_api_key --with-decryption \
  --query "Parameter.Value" --output text | grep -q "^replace-me$" \
  && echo "PLACEHOLDER KEY — fix first" || echo "key ok"

# 3. API healthy
curl -sS https://change-report.byraj.dev/api/healthz
```

Secrets are read by tasks **at start** — after changing an SSM value, force a
bounce on every task that reads it:

```sh
aws ecs update-service --cluster cci-prod --service cci-prod-api --force-new-deployment
aws ecs update-service --cluster cci-prod --service cci-prod-worker --force-new-deployment
```

## The flow (order matters — each step is the next one's prerequisite)

| # | Step | Expect |
|---|---|---|
| 1 | Upload agreement: `POST /documents` (multipart) | `status: uploaded` |
| 2 | `POST /documents/{id}/ingestion` → poll `GET /ingestion-jobs/{id}` (2s) | queued → completed, `result.chunk_count` > 0, document `parsed` |
| 3 | Upload amendment with `amends_document_id` → step 2 again | same |
| 4 | `POST /documents/{id}/extraction` ×2 → poll `GET /extraction-jobs/{id}` | completed with obligations + defined_terms |
| 5 | `POST /agreements/{agreement_id}/change-report` → poll `GET /change-report-jobs/{id}` | completed; review items for low-confidence output |
| 6 | `GET /review-items`, `GET /search?q=…`, `GET /usage/spend`, `GET /audit-log` | surfaces answer consistently with the jobs |

Negative tests at least once per session: re-enqueue while queued (409),
delete an agreement that has amendments (409), re-enqueue a failed job
(allowed — attempts count against the 3-cap).

Track per step: `date -u +%s` before enqueue → diff at the terminal poll =
**wall time**; subtract `usage/spend` `latency_ms` for the **LLM slice**; the
remainder is pipeline overhead (poll cadence, parse, DB writes).

## Where the logs are

Prod (CloudWatch, 14-day retention, JSON format):

```sh
aws logs tail /ecs/cci-prod-worker --since 10m --follow   # job lifecycle: "<kind> job queued/failed/completed/capped tenant=… job=…"
aws logs tail /ecs/cci-prod-api    --since 10m --follow   # request path; every line carries request_id=…
aws logs tail /ecs/cci-prod-migrate --since 1h            # migration runs (CI)
aws logs tail /ecs/cci-prod-api --since 30m --filter-pattern "<job-id>"
```

Local: `docker compose logs app -f` (API); `uv run python -m app.worker` in its
own terminal — **the one people forget to start**; ground truth via
`docker compose exec db psql -U postgres -d cci`.

Prod RDS is private; job state comes from the API endpoints, cost/latency from
`GET /usage/spend`.

## Alarms (automated, no watching required)

- `job failures ≥ 1 in 5 min` and `API errors ≥ 5 in 10 min` → SNS email
  (`infra/observability.tf`; owner confirms the subscription once). Idle gaps
  do not fire alarms (missing data is healthy).
- Sentry captures unhandled API exceptions and client-side UI failures
  (query-level errors included). Both are disabled while their DSN is empty.

## Logs Insights cheat sheet

```sql
-- Every job failure with its reason, last hour
fields @timestamp, message
| filter message like /job failed/
| sort @timestamp desc
| limit 50

-- One job's whole lifecycle across the worker stream
fields @timestamp, message
| filter message like /<job-id>/
| sort @timestamp asc

-- API 5xx by route (request_id joins API ↔ audit log)
fields @timestamp, request_id, message
| filter level = "ERROR"
| sort @timestamp desc
| limit 100
```

## After testing

```sh
aws ecs update-service --cluster cci-prod --service cci-prod-worker \
  --task-definition cci-prod-worker --desired-count 0   # idle-at-zero, decision #11
```
