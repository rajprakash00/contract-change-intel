# Progress

Current state + next tasks only. AGENTS.md owns commands and constraints,
CONTEXT.md the language, `docs/decisions/` the ADRs, `docs/w4-decisions.md`
the settled W4 design. When a block lands, compress it to a line here —
the file's history lives in git, not in this file.

## State

Done through **W4·D impact mapping**: W1 foundations / read paths /
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
`review.resolve`). Routing is additive — job results ship regardless.
`OPENAI_API_KEY` live and verified end to end; the 6 CUAD fixtures are
ingested in the dev DB under the eval tenant.

Baselines (`evals/baselines/`): retrieve recall@5 0.82 / recall@10 0.96;
extract precision 0.90 / recall 1.0 / citation_validity 1.0; diff
precision 1.0 / recall 1.0.
ruff/mypy clean; 303 integration+unit tests green.

## Open / blocked

- `ANTHROPIC_API_KEY` (owner) — blocks the Anthropic SDK spike.
- First GitHub Actions run unverified (CI is green locally).
- DELETE has no retention window; audit_log retention/read APIs deferred to
  review-queue work.
- Auth deferred to multi-tenancy work (W5).

## Next

Settled design: `docs/w4-decisions.md` (W4 complete) and `docs/w5-decisions.md`
(W5·A review queue → W5·B audit trail + impact-grading eval → W5·C OIDC auth
via Auth0; then W6·A thin Next.js UI → W6·B AWS ECS/RDS deploy via Terraform →
deployed API + UI + writeup with eval numbers). Deferred: rate limits, load
tests, Anthropic spike, retention.

## Gotchas

- Postgres job-status enum types are dropped explicitly in downgrades: table
  drops alone leak them and break re-upgrade.
- Delete-vs-amend race: an amendment inserted between `has_amendments` and
  the delete falls through to the RESTRICT FK and surfaces as a 500; to be
  handled if concurrent-write tests arrive.
