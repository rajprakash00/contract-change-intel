# Evals — golden-record fixtures

Golden datasets for the evaluation harness (W3+). Metrics to be measured:
extraction accuracy, citation validity, retrieval recall@k, task completion,
latency, cost.

## Metric definitions

Fixed targets so golden records have something stable to be scored against:

- **Citation validity** — fraction of Citations whose span exists in the
  document's parsed text and whose surrounding clause supports the statement.
  Checked mechanically against `document_sha256` + span offsets; "supports"
  judged against the golden record's expected clause.
- **Extraction accuracy** — precision/recall of extracted Obligations vs the
  golden record, matched on `clause_ref` + `owner`; description compared
  graded (not exact) since it is free text.
- **Retrieval recall@k** — fraction of golden-relevant Chunks present in the
  top-k search results for a golden query; reported at k=5 and k=10.
- **Diff detection accuracy** — precision/recall of detected Changes vs the
  golden record, matched on (`kind`, `clause_ref`); description and severity
  are free text and stay graded (not exact) until a grader exists. Identical
  versions score 1.0: "no change" is a graded outcome, not a division by zero.
- **Impact-mapping accuracy** — per Change, precision/recall of the mapped
  affected Obligations vs the golden affected list, matched on
  (`clause_ref`, `owner`, owner case-insensitive like extraction). A Change
  that affects nothing, mapped to nothing, scores 1.0: "affects nothing" is a
  graded outcome. Confidence calibration is not graded mechanically until a
  grader exists.
- **Task completion** — end-to-end Change Report on golden
  agreement/amendment pairs, judged against a human rubric (not automated
  until the rubric is written).
- **Latency / cost** — p50/p95 per pipeline stage and tokens + USD per
  document, both derived from the structured traces the LLM client already
  emits (no separate eval instrumentation).

## Format decision: JSONL, one record per line

Each golden record is one JSON object per line in `golden/*.jsonl`:

```json
{"id": "oblig-001", "task": "extract_obligations", "input": {"document_sha256": "...", "text": "Section 8.2 ..."}, "expected": {"obligations": [{"clause_ref": "8.2", "description": "...", "owner": "Supplier"}]}, "tags": ["termination", "handwritten"]}
```

- `id` — stable identifier; regressions are reported per id.
- `task` — pipeline function under test (`extract_obligations`, `diff`,
  `impact_map`, `retrieve`). One file per task keeps metrics separable:
  `golden/<task>.jsonl`.
- `input` — exactly what the function consumes; `document_sha256` ties the
  record to the stored source bytes for citation checking.
- `expected` — the known-good result, written by a human, checked by the
  harness (exact match where cheap, graded match where the field is free text).
- `tags` — category filters for slicing scores (clause type, difficulty,
  injection attempt, …).

Why JSONL over a database table: fixtures are versioned with the code, diff
cleanly in review, and load without infrastructure. If eval scale ever
outgrows files, the harness — not the format — moves.

`golden/` holds the first records (W3·D), drafted from the CUAD fixture
documents under `fixtures/cuad/` (CC BY 4.0, see its ATTRIBUTION.md): six
small, text-extractable contracts with diverse clause coverage, selected via
`master_clauses.csv`. The expected values were agent-drafted and have been
reviewed and approved by the owner. `fixture_shas.json` pins each fixture's
sha256; the tests in `tests/test_golden_records.py` fail fast if a fixture is
re-saved without regenerating the records keyed by it.

Seeding / re-seeding (needs `OPENAI_API_KEY` and the dev database, so it is a
manual step, not part of pytest):

```sh
uv run python -m evals.seed_fixtures   # uploads fixtures + ingests them
```

It seeds a fixed eval tenant (`00000000-0000-4000-8000-00000000c0ad`) so the
committed records' `tenant_id` stays valid across re-seeds, and is idempotent:
existing parsed uploads are skipped. It prints a manifest (sha256 + chunk
counts) for drafting; commit records, not the manifest.

Record caveats learned while drafting:

- `extract_obligations` `owner` matching is case-insensitive in the metric
  (contracts shout party names); beyond case it is exact, so golden owners use
  the party label as the clause itself names it.
- Extraction input text is an exact slice of the document's parsed text (built
  from chunk char ranges). Slices that straddle a cross-referenced clause
  produce legitimately ambiguous expectations — prefer self-contained clauses.
- The LLM runs at default temperature, so single-run precision on ambiguous
  text wobbles; interpret per-record scores as baselines, not determinisms.

## Harness

`evals/harness.py` runs a task's golden records through the real pipeline and
prints a JSON report (aggregate metrics + per-id scores, so regressions are
attributable):

```sh
uv run python -m evals.harness --task retrieve --k 5 --k 10
uv run python -m evals.harness --task extract_obligations
uv run python -m evals.harness --task diff
uv run python -m evals.harness --task impact_map
```

Per-task record shapes:

- `retrieve` — input `{"tenant_id", "query"}`; expected `{"chunks":
  [{"document_sha256", "ordinal"}]}`. A retrieved chunk is keyed by its
  document's sha256 plus its ordinal, which survives re-ingestion (chunk UUIDs
  do not). Scored with recall@k.
- `extract_obligations` — input `{"document_sha256", "text"}`; expected
  `{"obligations": [{"clause_ref", "owner"}]}`. Scored with precision/recall
  matched on (clause_ref, owner), plus mechanical `citation_validity` — the
  fraction of emitted citation spans that sit inside the record's text
  (`citation_spans_valid`). The service's citation gate drops uncited items on
  its final attempt (after one retry), so completed extractions carry only
  grounded spans and a lower score flags gate bypass or drift; a record whose
  extraction fails entirely (nothing grounded) scores zero across the board.
- `diff` — input `{"document_sha256", "base_text", "amended_text"}`; expected
  `{"changes": [{"kind", "clause_ref"}]}`. Scored with precision/recall
  matched on (kind, clause_ref). Pure pipeline (parse → clause-level
  alignment + diff, W4·C): no LLM in the loop, no database, so the task is
  cheap, deterministic, and needs no API key. The base text is a fixture's
  parsed text (pinned by sha256 like the other tasks); `amended_text` is a
  synthetic amendment of it, hand-labelled with the changes the edit makes.
- `impact_map` — input `{"document_sha256", "base_text", "amended_text",
  "obligations"}`; expected `{"changes": [{"kind", "clause_ref", "affected":
  [{"clause_ref", "owner"}]}]}`. Scored with per-Change precision/recall
  matched on (clause_ref, owner), averaged over the detected Changes. The
  texts run through the real parse + diff pipeline and each detected Change
  makes one real mapping call (app/services/impact.py) against the record's
  obligations as candidates — capped at the production CANDIDATE_LIMIT, so
  an API key is needed but no database. The record's obligations stand in
  for the candidate selection production performs (citation-overlap with
  retrieved chunks — pure logic, unit-tested). Affected lists are
  hand-labelled; a Change that affects no listed obligation expects `[]`.

Metric math is pure (`evals/metrics.py`, unit-tested); the harness only wires
records → pipeline → scores. Graded description comparison still awaits a
grader (free text is not exact-matchable), and the "surrounding clause
supports the statement" half of citation validity stays human-graded.
Task completion needs the human rubric. Latency/cost come from the
structured `llm call` traces, not this harness.

## Report storage: runs vs baselines

The harness prints its JSON report and, with `--out`, also writes it:

```sh
uv run python -m evals.harness --task retrieve --out evals/runs/2026-09-02-retrieve.json
```

Two places, two purposes:

- `evals/runs/` (gitignored) — raw run reports, local history only. Use it
  freely; per-run wobble (see the temperature caveat above) must not churn
  the public repo.
- `evals/baselines/<task>.json` (committed) — the curated snapshot of the
  accepted baseline: aggregate metrics, per-record scores, model and date.
  Update it deliberately: re-run, compare against the committed baseline,
  and overwrite only when the change is understood and accepted. Git then
  shows metric drift at milestone granularity.

A test in `tests/test_golden_records.py` locks each baseline's `per_record`
ids to exactly the golden record ids of its task, so adding or removing a
record without refreshing the baseline fails fast.
