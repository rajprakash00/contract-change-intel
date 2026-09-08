from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration; reads .env when present."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Driver is explicit in the URL because SQLAlchemy picks its driver from the scheme.
    # Host port 5433 matches docker-compose.yml (host 5432 belongs to another project here).
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/cci"

    log_level: str = "INFO"

    # Same-origin serving: the browser always says /api/...; the prefix is
    # stripped once here (dev: empty — Next rewrites proxy the bare API; prod:
    # /api — ALB path-routes without a rewrite layer). Never set per route.
    # docs/w6-decisions.md #6.
    root_path: str = ""

    # Root directory for uploaded files; files land at {data_dir}/{tenant_id}/{sha256}.
    data_dir: str = "./data"
    max_upload_mb: int = 50

    # LLM access (W2·A). Key comes from env only — never hardcoded, never logged.
    # Empty key means "LLM features disabled"; OpenAiClient raises
    # LlmNotConfiguredError at construction so this is visible at startup.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    # W3 ingestion embeddings (ADR-006): text-embedding-3-small is 1536-dim,
    # matching EMBEDDING_DIMENSIONS on DocumentChunk.
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: float = 60.0
    # Retries (with jittered backoff) and 429 handling are delegated to the SDK;
    # this only bounds how hard it tries before surfacing an LlmError.
    openai_max_retries: int = 2

    # W5·A review queue: LLM output whose Confidence falls strictly below the
    # per-job-kind threshold is routed to human review as a pending item.
    review_confidence_threshold_extraction: float = 0.7
    review_confidence_threshold_impact: float = 0.7

    # W5·C auth: OIDC bearer JWTs via Auth0. There is no "auth off" mode —
    # unconfigured auth surfaces 503 per request (same posture as the missing
    # OpenAI key), never a silently open API.
    auth0_domain: str = ""
    auth0_audience: str = ""
    # How long fetched JWKS keys stay trusted before a refetch.
    auth_jwks_cache_seconds: float = 600.0


@lru_cache
def get_settings() -> Settings:
    # Cached so request-scoped Depends() calls don't re-parse the environment per request.
    return Settings()
