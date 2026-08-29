# Evals — golden-record fixtures

Golden datasets for the evaluation harness (W3+). Metrics to be measured:
extraction accuracy, citation validity, retrieval recall@k, task completion,
latency, cost.

## Format decision: JSONL, one record per line

Each golden record is one JSON object per line in `golden/*.jsonl`:

```json
{"id": "oblig-001", "task": "extract_obligations", "input": {"document_sha256": "...", "text": "Section 8.2 ..."}, "expected": {"obligations": [{"clause_ref": "8.2", "description": "...", "owner": "Supplier"}]}, "tags": ["termination", "handwritten"]}
```

- `id` — stable identifier; regressions are reported per id.
- `task` — pipeline function under test (`extract_obligations`, `diff_explain`,
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

`golden/` is empty until the W3 ingestion pipeline produces the first
extractable documents; records are added with their source documents under
`fixtures/` at that point.
