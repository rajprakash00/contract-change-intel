# Contract Change-Impact Intelligence

A service that reads agreements and their amendments, extracts obligations, explains
what changed between versions, and maps each change onto the obligations it affects.

## Language

### Objects

**Agreement**:
A contract document uploaded to the system; the root object whose versions get compared.
_Avoid_: contract, document

**Amendment**:
A later version of an Agreement, uploaded as its child.
_Avoid_: revision, redline

**Document**:
The stored bytes behind an Agreement or Amendment upload — a code-level container, not
a domain word.
_Avoid_: file, upload (as noun)

**Tenant**:
The customer organization using the system; every object is scoped to one.
_Avoid_: customer, org, account

**Demo Tenant**:
The published sandbox tenant (dedicated UUID, credentials in the README) where
visitors try the product under a reduced hourly budget, on artifacts they
upload themselves.
_Not a sales funnel and not the operator's tenant._
_Avoid_: trial tenant, sandbox (bare), test tenant

### Ingesting

**Ingestion**:
Preparing an uploaded Document for search and citation: turning its text into Chunks.
Precedes Extraction, which reads the same text.
_Avoid_: parsing, indexing, processing

**Chunk**:
A span of an Agreement version's text; the unit that gets retrieved and cited.
Not an Obligation and not a Citation — Citations may point at Chunks, Obligations are
read from them.
_Avoid_: passage, segment, fragment, paragraph

### Reading

**Extraction**:
Reading a version of an Agreement and producing Obligations and Defined Terms, each
with Citations.
_Avoid_: parsing, processing

**Obligation**:
A duty extracted from an Agreement version: who must do what by when, at what penalty.
_Avoid_: requirement, clause item

**Defined Term**:
A word or phrase the Agreement itself defines ("Termination Date means…"); extracted
alongside Obligations, not one of them.
_Avoid_: definition (bare)

**Citation**:
A pointer back to where a statement came from in the source text.
_Avoid_: reference, source span

### Comparing versions

**Change**:
A single difference between two versions of an Agreement: added, modified, or removed.
_Avoid_: diff (as noun), delta, issue

**Severity**:
How seriously a Change matters: low, medium, or high.
_Avoid_: risk, priority

**Impact**:
The mapping from a Change to the Obligations it touches.
_Avoid_: consequence, risk

**Change Report**:
The per-Amendment output: extracted Obligations, explained Changes, Impact map,
Citations and Confidence, flagged Review Items.
_Avoid_: delta, comparison, impact analysis, report

**Sample Report**:
A Change Report snapshot generated from a real run and shown on the landing page to
signed-out visitors; never a mockup.
_Avoid_: demo report, mockup

### Report reliability

**Stable Report**:
A Change Report whose Changes, Impacts, and Severities agree with a re-run on the same
inputs within the evaluation tolerance.
_Avoid_: deterministic report (bare), consistent report

**Replayable Report**:
A Change Report that can be regenerated from its recorded inputs and Provenance without
new model calls.
_Avoid_: cached report, deterministic report (bare)

**Provenance**:
The recorded origin of a Change Report: the model, prompt version, sampling parameters,
and input fingerprints that produced it.
_Avoid_: metadata, trace

### Review

**Confidence**:
A 0–1 score attached to each extraction and Impact; below the Tenant's threshold, the
item becomes a Review Item.
_Avoid_: certainty, score (bare)

**Review Item**:
An extraction or Impact flagged for a human because its Confidence fell below the
threshold; pending until a Reviewer applies a Disposition.
_Avoid_: flag, exception, queue entry

**Reviewer**:
The human who resolves Review Items.
_Avoid_: admin, user (bare)

**Disposition**:
A Reviewer's resolution of a Review Item: approved, edited, or rejected.
_Avoid_: decision, status, resolution
