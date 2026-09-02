"""Seed the dev database with the CUAD fixture documents (W3·D).

Uploads fixtures/cuad/*.pdf into the fixed eval tenant and runs each
document's ingestion to completion (real embeddings; needs OPENAI_API_KEY
and a reachable database — docker compose up -d --wait first). Safe to
re-run: existing uploads are skipped, ingestion only runs for documents
not yet parsed.

The printed manifest (filename → sha256, chunk count) is the drafting
input for evals/golden/<task>.jsonl; commit the records, not the manifest.

    uv run python -m evals.seed_fixtures
"""

import asyncio
import hashlib
import json
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.repositories.documents as documents_repo
from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.llm.client import OpenAiClient
from app.models.document import DocumentStatus
from app.models.ingestion_job import IngestionJob, IngestionJobStatus
from app.services.documents import DocumentAlreadyExistsError, upload_document
from app.services.ingestion import (
    IngestionJobConflictError,
    enqueue_ingestion,
    get_ingestion_job,
    run_next_ingestion_job,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "cuad"

# Fixed so golden records can hardcode tenant_id and keep working across
# re-seeds; a random tenant would orphan the committed records on every run.
EVAL_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-00000000c0ad")

# Bounded because run_next_ingestion_job claims any queued job in the
# database, not just ours; a dev DB with a job backlog needs more passes.
_MAX_WORKER_PASSES = 50


async def _seed_document(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    settings: Settings,
    path: Path,
) -> dict[str, object]:
    """Upload one fixture (skipping an existing upload) and ingest it; the
    repositories commit their own writes, so no explicit commit happens here."""
    content = await asyncio.to_thread(path.read_bytes)
    consumed = False

    async def read(_size: int) -> bytes:
        nonlocal consumed
        if consumed:
            return b""
        consumed = True
        return content

    async with session_maker() as session:
        try:
            document = await upload_document(
                session,
                tenant_id=EVAL_TENANT_ID,
                filename=path.name,
                content_type="application/pdf",
                read=read,
                data_dir=settings.data_dir,
                max_bytes=settings.max_upload_mb * 1024 * 1024,
            )
        except DocumentAlreadyExistsError:
            existing = await documents_repo.find_by_sha256(
                session, tenant_id=EVAL_TENANT_ID, sha256=hashlib.sha256(content).hexdigest()
            )
            if existing is None:
                raise RuntimeError(f"{path.name}: dedupe fired but no document row found") from None
            if existing.status is DocumentStatus.parsed:
                return {"filename": path.name, "sha256": existing.sha256, "skipped": True}
            document = existing

        try:
            job = await enqueue_ingestion(
                session, tenant_id=EVAL_TENANT_ID, document_id=document.id
            )
        except IngestionJobConflictError as exc:
            raise RuntimeError(
                f"{path.name}: active ingestion job {exc.job_id} — wait or inspect manually"
            ) from exc

    job = await _drive_to_terminal(session_maker, llm, settings.data_dir, job.id)
    if job.status is not IngestionJobStatus.completed:
        raise RuntimeError(f"{path.name}: ingestion failed: {job.error}")
    return {
        "filename": path.name,
        "sha256": document.sha256,
        "chunk_count": job.result.get("chunk_count") if job.result else None,
    }


async def _drive_to_terminal(
    session_maker: async_sessionmaker[AsyncSession],
    llm: OpenAiClient,
    data_dir: str,
    job_id: uuid.UUID,
) -> IngestionJob:
    """Run worker passes until the given job reaches a terminal state."""
    for _ in range(_MAX_WORKER_PASSES):
        async with session_maker() as session:
            job = await get_ingestion_job(session, tenant_id=EVAL_TENANT_ID, job_id=job_id)
            if job.status in (IngestionJobStatus.completed, IngestionJobStatus.failed):
                return job
            await run_next_ingestion_job(session, llm=llm, data_dir=data_dir)
    raise RuntimeError(f"ingestion job {job_id} never reached a terminal state")


async def main() -> None:
    settings = get_settings()
    llm = OpenAiClient(settings)  # raises LlmNotConfiguredError without a key
    init_engine(settings.database_url)
    session_maker = get_sessionmaker()
    manifest: list[dict[str, object]] = []
    try:
        for path in sorted(FIXTURES_DIR.glob("*.pdf")):
            entry = await _seed_document(session_maker, llm, settings, path)
            print(f"seeded {path.name}: {entry}", flush=True)
            manifest.append(entry)
    finally:
        await llm.aclose()
        await dispose_engine()
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
