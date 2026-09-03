# Progress

Current state + next tasks only. AGENTS.md owns commands and constraints,
CONTEXT.md the language, `docs/decisions/` the ADRs, `docs/w4-decisions.md`
the settled W4 design. When a block lands, compress it to a line here —
the file's history lives in git, not in this file.

## State

Done through **W4·B amendment linking**: W1 foundations / read paths /
hardening gate · W2 LLM client + extraction job surface · W3 ingestion
pipeline (parse → chunk → embed), RRF hybrid search, golden records + eval
harness · W4·A parse-gated extraction (409 until ingestion completes), worker
reads parsed text from `document_texts`, citation gate with one retry that
drops uncited items on the final attempt, `Citation` / clamped `Confidence`
(ADR-007) / `DefinedTerm` schema · W4·B `documents.amends_document_id`
self-FK (RESTRICT; parent deletes 409 while amendments exist) +
`amends_document_id` form field on `POST /documents`, tenant-scoped parent
validation (404 unknown/foreign parent; duplicate bytes still 409).
`OPENAI_API_KEY` live and verified end to end; the 6 CUAD fixtures are
ingested in the dev DB under the eval tenant.

Baselines (`evals/baselines/`): retrieve recall@5 0.82 / recall@10 0.96;
extract precision 0.90 / recall 1.0 / citation_validity 1.0.
ruff/mypy clean; 217 integration+unit tests green.

## Open / blocked

- `ANTHROPIC_API_KEY` (owner) — blocks the Anthropic SDK spike.
- First GitHub Actions run unverified (CI is green locally).
- DELETE has no retention window; audit_log retention/read APIs deferred to
  review-queue work.
- Auth deferred to multi-tenancy work (W5).

## Next

Settled design: `docs/w4-decisions.md` (ADRs land with the blocks that need
them; ADR-007 is written).

- **W4·C** — clause-level alignment + pure diff; `change_report_jobs` + Change
  Report HTTP surface; one structured explanation call per version pair;
  `diff` golden task in the eval harness.
- **W4·D** — document-scoped search variant + impact mapping with per-Impact
  Confidence.

## Gotchas

- Postgres job-status enum types are dropped explicitly in downgrades: table
  drops alone leak them and break re-upgrade.
- Delete-vs-amend race: an amendment inserted between `has_amendments` and
  the delete falls through to the RESTRICT FK and surfaces as a 500; to be
  handled if concurrent-write tests arrive.
