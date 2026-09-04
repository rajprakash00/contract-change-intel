"""Worker process: round-robin claims across the job tables.

Run with `uv run python -m app.worker`. Jobs are Postgres rows; concurrent
workers are safe via FOR UPDATE SKIP LOCKED (see
app/repositories/job_claims.py). Fails fast at startup when no API key is
configured — LlmNotConfiguredError is a deployment problem, not a per-job
failure.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

import app.db as db
from app.config import Settings, get_settings
from app.llm.client import OpenAiClient
from app.logging_config import configure_logging
from app.services import change_report, extraction, ingestion

logger = logging.getLogger(__name__)

_POLL_SECONDS = 2.0
_QUEUE_COUNT = 3


async def run_next_job(
    session: AsyncSession, *, llm: OpenAiClient, data_dir: str, first: int
) -> bool:
    """One pass over the queues starting at rotation index `first`; True when a
    job was claimed. Each queue is tried at most once per pass, so a backlog in
    one queue cannot starve the others. Extraction reads parsed text from the
    database; ingestion alone needs the storage data_dir."""
    queues: tuple[Callable[[], Awaitable[bool]], ...] = (
        lambda: extraction.run_next_extraction_job(session, llm=llm),
        lambda: ingestion.run_next_ingestion_job(session, llm=llm, data_dir=data_dir),
        lambda: change_report.run_next_change_report_job(session, llm=llm),
    )
    for offset in range(len(queues)):
        if await queues[(first + offset) % len(queues)]():
            return True
    return False


async def main() -> None:
    settings: Settings = get_settings()
    configure_logging(settings.log_level)
    llm = OpenAiClient(settings)  # raises LlmNotConfiguredError when the key is missing
    db.init_engine(settings.database_url)
    logger.info(
        "worker starting model=%s embedding_model=%s",
        settings.openai_model,
        settings.openai_embedding_model,
    )
    turn = 0
    try:
        while True:
            async with db.get_sessionmaker()() as session:
                ran = await run_next_job(session, llm=llm, data_dir=settings.data_dir, first=turn)
            turn = (turn + 1) % _QUEUE_COUNT
            # Rotate every pass; idle briefly only when no queue had work.
            if not ran:
                await asyncio.sleep(_POLL_SECONDS)
    finally:
        await llm.aclose()
        await db.dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
