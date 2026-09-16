import json
import logging
import logging.config
from datetime import UTC, datetime

from app.request_context import current_request_id


class RequestIdFilter(logging.Filter):
    """Attach the active request id to every record; '-' outside requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        return True


def configure_logging(level: str = "INFO", log_format: str = "console") -> None:
    """Single place that wires root logging; called once from the app lifespan
    and the worker entrypoint.

    Console text for local development; JSON for deployed tasks (ADR
    observability): the CloudWatch metric filters (infra/observability.tf)
    key on the stable top-level fields, and any future log shipper wants the
    same contract.
    """
    formatter = "json" if log_format == "json" else "text"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdFilter},
            },
            "formatters": {
                "text": {
                    "format": (
                        "%(asctime)s %(levelname)-8s request_id=%(request_id)s %(name)s %(message)s"
                    ),
                },
                "json": {
                    "()": JsonFormatter,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": formatter,
                    "filters": ["request_id"],
                },
            },
            "root": {"handlers": ["console"], "level": level.upper()},
        }
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per log line with stable top-level keys: ts, level,
    logger, request_id, message (plus exc when present). No dynamic extras —
    call sites pass context through %-args so the message already carries it."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def init_sentry(dsn: str, environment: str = "") -> None:
    """Capture unhandled exceptions to Sentry when a DSN is configured;
    disabled (no-op) otherwise — the missing-DSN posture matches the missing
    OpenAI key and auth settings: a deployment choice, never a runtime error.
    Registered in both processes (api lifespan, worker main) so neither can
    lose errors to the other's blind spot. The optional environment label
    separates prod events from local ones in one project; the SDK's default
    ("production") stands in when unset."""
    if not dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=environment or None,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
        # Error capture only: the job tables already measure latency.
        traces_sample_rate=0.0,
    )
