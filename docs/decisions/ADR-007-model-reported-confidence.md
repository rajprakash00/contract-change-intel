# ADR-007: Model-reported Confidence

## Context

Extraction (W4·A) emits Obligations and Defined Terms that downstream work —
Change Reports, impact mapping, review routing — must weigh. Some extracted
items are dead-on ("Supplier shall pay within 30 days"); others are guesses at
paraphrase or scope. The pipeline needs a per-item signal for how sure the
extraction is, so low-confidence output can be routed to human review (W5)
instead of silently entering the Change Report.

There is no mechanical way to derive this signal today: span validity is a
correctness check (an item either cites real text or it does not — see the
citation gate in `app/services/extraction.py`), and the judge of whether the
*cited* passage actually supports the claim is, for now, the model itself.

## Decision

Confidence is **model self-reported**: the extraction schema carries a
`confidence` float (0–1) per Obligation and Defined Term, prompted as "the
model's confidence in this extraction".

- **Clamped, not rejected.** Out-of-range values are clamped into [0, 1] by a
  validator, not failed. A validator (not JSON-Schema `minimum`/`maximum`
  constraints, which OpenAI strict structured outputs does not support) keeps
  the wire schema plain, and an overconfident 1.7 is worth clamping, not
  discarding the whole extraction.
- **Not a mechanical-signal input.** Confidence never feeds validation
  checks like span validity; it is one number the model reports beside its
  claim. Mechanical grounding stays the citation gate's job.
- **Consumed downstream, calibrated never assumed.** W4·D maps per-Change
  Impacts with per-Impact Confidence; the review queue (W5) routes on it. The
  number is a ranking signal, not a probability.

## Consequences

- The schema must carry the field from the start; retrofitting confidence
  into stored extraction results would orphan earlier job rows.
- Self-reported confidence is known to be poorly calibrated (models are
  overconfident); the evals track extraction precision/recall so review
  thresholds can be tuned against observed accuracy, not the raw number.
- No extra LLM calls or cost: confidence rides along in the single
  structured-output call per document.

## Rejected alternative

Mechanical confidence (derive a score from span length, chunk rank, or
agreement between candidates) — none of these measure whether the statement
is *supported*, and inventing a pseudo-probability hides that the only
available judge today is the model. A calibrated external judge (e.g. a
second verification pass) is a future option if review routing shows the
self-reported number is too coarse.
