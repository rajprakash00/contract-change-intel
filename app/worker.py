"""Worker process: claims queued extraction jobs and runs them.

Run with `uv run python -m app.worker`. Jobs are Postgres rows; concurrent
workers are safe via FOR UPDATE SKIP LOCKED (see
app/repositories/extraction_jobs.py). Fails fast at startup when no API key
is configured — LlmNotConfiguredError is a deployment problem, not a
per-job failure.
"""

import asyncio
import logging

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, init_engine
from app.llm.client import OpenAiClient
from app.logging_config import configure_logging
from app.services import extraction

logger = logging.getLogger(__name__)

_POLL_SECONDS = 2.0


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    llm = OpenAiClient(settings)  # raises LlmNotConfiguredError when the key is missing
    init_engine(settings.database_url)
    logger.info("extraction worker starting model=%s", settings.openai_model)
    try:
        while True:
            async with get_sessionmaker()() as session:
                ran = await extraction.run_next_extraction_job(
                    session, llm=llm, data_dir=settings.data_dir
                )
            # Poll immediately after work (drain the queue); idle briefly otherwise.
            if not ran:
                await asyncio.sleep(_POLL_SECONDS)
    finally:
        await llm.aclose()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
