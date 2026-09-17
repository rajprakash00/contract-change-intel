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

## Usage & audit observation (per step)

Role gates differ (app/api/deps.py): `/usage/spend` is **admin only**,
`/audit-log` any authenticated tenant principal. Tenant comes from the token.

Setup once per session:

```sh
export API=https://change-report.byraj.dev/api
export TOKEN=<jwt>          # Auth0 bearer token for the test tenant
curl -sS -H "Authorization: Bearer $TOKEN" "$API/healthz"
```

Snapshot helpers — `spend` defaults to `group_by=job` (one row per job: calls,
prompt/completion tokens, `cost_usd`, `latency_ms`) for before/after deltas
around a single step; `spend job_type` gives coarse per-kind totals for
session start/end. Each audit row's `request_id` joins to CloudWatch
(`--filter-pattern "<request_id>"` on the API stream, job UUID on the worker
stream).

```sh
spend() { curl -sS -H "Authorization: Bearer $TOKEN" \
  "$API/usage/spend?group_by=${1:-job}" | python3 -m json.tool; }

audit() { curl -sS -H "Authorization: Bearer $TOKEN" \
  "$API/audit-log?limit=100${1:+&action=$1}" | python3 -m json.tool; }
```

| When | Run | Audit action filter | Confirming |
|---|---|---|---|
| Session baseline | `spend job_type; audit` | — | record totals to diff at end |
| After upload | `audit document.upload` | `document.upload` | one row per upload attempt; sha/size in `detail` |
| After ingestion | `spend; audit ingestion.enqueue` | `ingestion.enqueue` | embeddings cost row (embed model, no completion tokens) |
| After extraction | `spend; audit extraction.enqueue` | `extraction.enqueue` | cost row per job; re-extract = second row — diff the two |
| After report | `spend; audit change_report.enqueue` | `change_report.enqueue` | diff + explanation + impact calls land on one job's row |
| Review resolution | `audit review_item.resolve` | `review_item.resolve` | 409 on double-resolve → no second row |
| Rate-limit test | `spend` during 429s | — | spend frozen while 429ing; resumes after window |
| Session end | `spend job_type; audit` | — | final totals = baseline + observed deltas |

Polling pattern inside a step (verified against prod 2026-09-16). Capture ids
from responses or the document list — never hand-copy them; a stale or
foreign-tenant id is the most common 404.

```sh
# Mode A — reuse a document already in prod (all stress/re-run scenarios).
# No local file needed; upload happens only for new bytes (Mode B).
curl -sS -H "Authorization: Bearer $TOKEN" "$API/documents?limit=20" \
  | python3 -c "import json,sys; \
[print(d['id'], d['status'], d['filename'], sep='  ') for d in json.load(sys.stdin)['items']]"
DOC=<id>            # pick a row — prefer one with status parsed

# Mode B — fresh bytes (first-run flow, dedup/409 test). curl reads the file
# locally, so the path is relative to your cwd; curl (26) = file not found.
DOC=$(curl -sS -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@agreement.txt;type=text/plain" "$API/documents" \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))")

# precheck before enqueue — catches id/tenant mistakes with a readable error
curl -sS -H "Authorization: Bearer $TOKEN" "$API/documents/$DOC" | python3 -m json.tool

# enqueue → poll → observe (endpoint varies per step, see table below)
t0=$(date -u +%s)
RESP=$(curl -sS -w '\n%{http_code}' -X POST \
  -H "Authorization: Bearer $TOKEN" "$API/documents/$DOC/extraction")
echo "$RESP" | tail -1        # HTTP code first: 202 enqueued; else read the body
JOB=$(echo "$RESP" | head -1 | python3 -c \
  "import json,sys; print(json.load(sys.stdin).get('id',''))")

until curl -sS -H "Authorization: Bearer $TOKEN" "$API/extraction-jobs/$JOB" \
    | python3 -c "import json,sys; sys.exit(0 if json.load(sys.stdin).get('status') in ('completed','failed') else 1)"; do sleep 2; done
echo "wall=$(( $(date -u +%s) - t0 ))s"
spend | python3 -c "import json,sys; j='$JOB'; print(*[r for r in json.load(sys.stdin)['rows'] if r.get('job_id')==j], sep='\n')"
```

Per-step endpoints and the one real timing gate (everything else enqueues
from any state):

| Step | Enqueue POST | Poll GET | Timing gate |
|---|---|---|---|
| Ingestion | `/documents/$DOC/ingestion` | `/ingestion-jobs/$JOB` | none |
| Extraction | `/documents/$DOC/extraction` | `/extraction-jobs/$JOB` | document must be `parsed` first, else 409 |
| Change report | `/agreements/$AGREEMENT/change-report` | `/change-report-jobs/$JOB` | both docs `parsed` + latest completed extraction, else 409 |

Failure decode — read the HTTP code, then the body (`{"detail": …}`):

| Code | Meaning |
|---|---|
| 404 | `$DOC`/`$AGREEMENT` wrong, stale, or belongs to another tenant — re-capture, not a timing issue |
| 409 | State/timing or conflict: doc not `parsed`, a job already queued/running (body names the blocking job), doc has amendments |
| 429 | LLM budget exhausted; `Retry-After` gives the window reset |

`wall − latency_ms` = pipeline overhead — note it per scenario; re-runs expose
queue/claim delays.

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
