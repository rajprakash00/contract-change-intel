# ADR-001: Content-addressed document storage layout

## Context

Uploaded documents must be persisted as bytes before any parsing exists, in a
layout that will survive later object-storage migration and concurrent uploads
of identical files.

## Decision

Store bytes at `{DATA_DIR}/{tenant_id}/{sha256}` — path derived from the
tenant id and the SHA-256 of the content. All byte IO lives in
`app/storage/local.py`; nothing else touches the filesystem.

Consequences:

- **Duplicate detection is O(1)**: compute hash, check row existence (409 on hit).
- **Re-uploading identical bytes** overwrites itself atomically (`os.replace`),
  so the **duplicate-race path needs no orphan cleanup**.
- **Deleting a document** is a plain unlink; a crash between row deletion and
  unlink leaves **at worst an orphan file, never a dangling row or db crash.**
- Identical content shared across tenants **costs double disk space**; acceptable
  until storage cost becomes an eval metric.

## Rejected alternative

Timestamp- or uuid-named files under tenant directories. Rejected because it
needs a second dedupe mechanism, makes integrity verification impossible, and
complicates the later move to object storage (content addressing maps directly
to S3-style key layouts).
