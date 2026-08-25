from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration; reads .env when present."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Driver is explicit in the URL because SQLAlchemy picks its driver from the scheme.
    # Host port 5433 matches docker-compose.yml (host 5432 belongs to another project here).
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/cci"

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    # Cached so request-scoped Depends() calls don't re-parse the environment per request.
    return Settings()
