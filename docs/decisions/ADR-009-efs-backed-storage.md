# ADR-009: EFS for Content-Addressed Upload Storage

## Context

ADR-001 put uploaded bytes in a content-addressed filesystem layout
(`{data_dir}/{tenant_id}/{sha256}`) behind the `app/storage` layer, with the
explicit promise that swapping the backing store touches only that module.
Local dev and docker-compose satisfy that with bind volumes. W6·B deploys the
API and worker as Fargate tasks (docs/w6b-decisions.md), where task local disk
is ephemeral and per-task: every task replacement — deploy, OOM kill, scale
event — would silently lose every uploaded file, and the ingestion worker
reads bytes the API wrote, so the two must share one durable volume. The
system is deployed for a demo window with teardown planned afterwards.

## Decision

**Amazon EFS, mounted at `data_dir` on the API and worker task definitions
(EFS volume configuration, transit encryption on). `app/storage` is
unchanged.**

The content-addressed layout, tenant subdirectories, and `asyncio.to_thread`
disk IO path all carry over untouched; the only change is which filesystem is
behind the mount point. Throughput mode general-purpose/elastic at demo scale
(tens of documents) is far above need, and EFS cost is negligible at that
volume.

## Consequences

- Upload writes and worker reads see one namespace; no re-plumb of either.
- A shared mutable filesystem is a coarser primitive than per-object keys;
  fine at this scale, and the seam for S3 remains where it always was.
- Task definitions gain the EFS mount + the EFS access point config; IAM
  gains the EFS mount-target access role.

## Rejected alternatives

- **S3-backed `app/storage`** — the architecturally "native" cloud answer and
  the right one if this system ever grows, but it means rewriting the storage
  module, adding IAM + a config knob, and losing the filesystem parity that
  currently keeps local/dev and prod identical — all for a demo whose bytes
  fit in a coffee cup. The ADR-001 seam is kept for the day a second real use
  justifies the port.
- **Per-task EBS / task-local disk only** — EBS volumes cannot attach to
  multiple Fargate tasks, so the worker could not read what the API wrote;
  task-local disk alone loses bytes on every task replacement.
- **Single long-lived task with retries to avoid replacement** — turns every
  deploy into a data-loss event and fights the job/lease design instead of
  using it.
