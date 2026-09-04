# W4 — change intelligence: settled decisions

Settled in the W4 grill session; recorded here until each block's ADR lands.
Slice order: **W4·B amendment linking → W4·C explanation + diff eval → W4·D
impact mapping**. Review queue + multi-tenancy/RBAC stay in W5.

## Amendment model (W4·B)

Self-referential nullable FK `documents.amends_document_id`; no separate
versions table. Revisit trigger: multiple chains / ordering semantics.
The FK is `ON DELETE RESTRICT`: a document with surviving amendments
cannot be deleted (DELETE returns 409 until the chain is removed leaf
first) — an audited system does not silently cascade or unlink.

## Linking API (W4·B)

Optional `amends_document_id` form field on the existing `POST /documents`;
tenant-scoped parent validation (404 unknown parent, 409 self/duplicate bytes).
Any Document may parent many Amendments; chains allowed. Change Reports diff
exactly the two named documents, never collapsed chains.

## Change grounding (W4·C)

Clause-level alignment: match chunks across versions by clause_ref/heading with
a number-normalization rule ("8.02" → "8.2"; guard against "8.2" vs "8.2.1"
child-clause collisions). Pure diff within matched pairs + unmatched groups;
each Change carries char spans into both versions' parsed text. Unit-tested
pure logic, checked against the 6 CUAD fixtures.

Implementation notes (W4·C build): alignment sections are derived from each
version's *parsed text paragraphs*, not its chunks — the chunker's
fixed-window fallback for heading-less documents (ADR-005) collapses
plain-text agreements into one chunk, which would degenerate alignment to a
whole-document diff; paragraph structure is the common denominator of every
parser. The prerequisite 409 names the first gap in the order base-ingestion →
base-extraction → amendment-ingestion → amendment-extraction.

## Change Report surface (W4·C)

`change_report_jobs` table (third sibling of the ADR-004 job family).
`POST /agreements/{id}/change-report` naming the amendment → 202; poll
`GET /change-report-jobs/{id}`. Prerequisites: 409 with detail naming the first
missing job (ingestion or extraction on either version); the caller drives
everything explicitly.

## Explanation (W4·C)

One structured-output call per version pair; per-Change description + severity
(low/medium/high). No summary paragraph.

## Diff eval (W4·C)

Add a `diff` golden task (mechanical precision/recall on detected Changes).
Impact grading deferred to W5 — the mapping must exist first.

## Impact mapping (W4·D)

Per Change, hybrid search over the *base version's chunks only* (the search
repo needs a document-scoped variant; `GET /search` is tenant-wide), then one
structured call maps Change + candidates → affected Obligations with
per-Impact Confidence (ADR-007).

## Owner decisions

- Re-extraction: status quo stays — `enqueue_extraction` blocks only
  queued/running; re-run after a `completed` job remains allowed.
