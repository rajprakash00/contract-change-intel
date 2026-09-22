# W7: settled decisions

Settled in the W7 grill session (2026-09-22), after the post-W6 review.
Destination is **portfolio depth**, not productization: every workstream must
produce a number, a gate, or a visible surface. Order is deliberately
showcase-first — the published link currently dead-ends strangers on a landing
page plus an Auth0 wall, so the product must show its value before any further
backend depth. Three blocks; the W6 pattern of a decisions doc per block holds,
this file is the umbrella.

## Block order and rationale

- **W7·A — Showcase & UI** (first): a visitor must understand the product and
  reach a working demo without reading GitHub; the change report is the
  product's core value and must become legible.
- **W7·B — Reliability & latency**: the demo now runs continuously, so the
  queue must be trustworthy (no double-spend, no lost review items) and its
  latency measured, not assumed.
- **W7·C — Evals & determinism**: with the surfaces and numbers in place, the
  eval harness becomes a regression gate and run-to-run report variation gets
  a measured definition and provenance.

Deferred to W8 (deliberately, to keep W7 at three blocks): Redis-backed rate
limiter (multi-replica, ADR-010), retention/PII policy, Playwright e2e,
OTel-style trace export, a public benchmark anchor (LegalBench-RAG-mini first
choice), `favorability` on Change, anonymous demo sessions, search/admin UI
fast-follows if W7·A runs long.

## W7·A — Showcase & UI

1. **Landing showcase.** A real **Sample Report** — a committed JSON artifact
   generated from the demo tenant's actual change-report output by a script in
   `scripts/` — rendered on the landing page for signed-out visitors. A "Try
   the demo" button prefills the demo email via Auth0 `login_hint`; the demo
   password is displayed with a copy button. No anonymous token minting
   (ADR-012). A short GIF in the README is optional later.
2. **Report payload.** Each Change in `change_report_jobs.result` gains
   `base_excerpt` / `amended_excerpt` — the exact parsed-text slice at the
   recorded span, capped — so a report is self-contained and snapshot-
   consistent. No parsed-text fetch endpoint.
3. **Report view redesign.** Before/after excerpts (redline-ish reading),
   severity grouping with counts, links to both documents, job metadata,
   real loading/error states, and a print/export memo (print stylesheet plus
   copy-as-Markdown).
4. **Review queue.** Detail view plus a structured edit form per item kind,
   replacing the raw-JSON textarea.
5. **Responsive, dark mode, a11y pass.** `impeccable` skill drives it; dark
   mode gets a real provider/toggle.
6. **Fast follows if room:** search page (backend exists), admin spend +
   audit pages (APIs exist).
7. **Deploy posture.** `api`/`ui`/`worker` run at desired 1 while the
   portfolio link is published; `scripts/demo-up.sh` / `demo-down.sh` are the
   one-command lifecycle, documented in the runbook with the monthly cost
   delta. Returning the worker to 0 waits for W7·B autoscaling.

## W7·B — Reliability & latency

1. **Stage timing.** `started_at`/`finished_at` on the three job tables
   (migration), queue-wait and run-time in logs and CloudWatch metrics,
   alarms for queue depth and job duration, worker autoscale on backlog.
2. **Lease heartbeat + per-job timeout + retry backoff.** The 15-minute lease
   is currently never renewed, so a long report can be double-claimed and
   double-spent.
3. **Active-job guard for change reports** (409, matching extraction's
   conflict behavior) so duplicate enqueues cannot burn budget.
4. **Atomic review-item routing** with job completion, closing the
   crash-window where a completed job's items are never created.
5. **Bounded parallel per-Change impact mapping** plus a lifespan-scoped LLM
   client (today `GET /search` builds a fresh client per request).
6. **Load harness.** Committed asyncio/httpx script plus a local fixture JWKS
   server (reusing `tests/fake_jwks.py` keys) so no auth-off mode is needed;
   scenarios: full pipeline (primary) and search QPS (secondary). Output is a
   self-contained HTML report (percentiles, throughput, errors, cost) plus
   JSON, committed as a shareable artifact.

Numbers to publish: queue-wait p95, upload→report wall time before/after,
pipeline throughput, cost per report.

## W7·C — Evals & determinism

1. **Eval gate.** `evals.yml` workflow: weekly schedule + `workflow_dispatch`,
   live models, comparison against committed baselines, non-zero exit when
   any metric drops more than 0.05 absolute or 10% relative, report in the
   job summary plus artifact. Owner prerequisite: `OPENAI_API_KEY` repo
   secret.
2. **Golden expansion.** impact 2→8, diff 2→6, retrieve 12→20 records.
3. **Stability@3.** Three runs per task; per-metric agreement across runs is
   the measured definition of a **Stable Report**.
4. **LLM-judge** for explanation quality and severity agreement (the free-text
   half of the report, currently ungraded).
5. **Adversarial prompt-injection task** — synthetic contracts carrying
   injected instructions; assert they are never obeyed. Lands if the block
   has room; rationale already lives in `docs/llm-boundaries.md`.
6. **Determinism and provenance.** Sampling settings (temperature/seed) as
   configuration; model, prompt version, sampling parameters, and input
   fingerprints persisted with results; a replay path that regenerates a
   **Replayable Report** from recorded inputs without new model calls.
   Duplicate-run guards from W7·B are the other half of replayability.
7. **Stretch:** LegalBench-RAG-mini as the first external-comparability
   anchor (chunks already carry character spans).

ADR for report determinism/provenance is written in this block.

## Cross-cutting

- Each block ends with a PROGRESS line; README gets a numbers refresh at the
  end of W7.
- Same-sha deploy rerun guard is a chore for whenever `deploy.yml` is next
  touched.
- ADR-012 (published demo access) ships with W7·A.
