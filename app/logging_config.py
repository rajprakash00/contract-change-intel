import logging
import logging.config

from app.request_context import current_request_id


class RequestIdFilter(logging.Filter):
    """Attach the active request id to every record; '-' outside requests."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    """Single place that wires root logging; called once from the app lifespan.

    Console text format is deliberate for local development; structured JSON
    logging belongs to the deployment milestone, not day one.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "request_id": {"()": RequestIdFilter},
            },
            "formatters": {
                "default": {
                    "format": (
                        "%(asctime)s %(levelname)-8s request_id=%(request_id)s %(name)s %(message)s"
                    ),
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                },
            },
            "root": {"handlers": ["console"], "level": level.upper()},
        }
    )
