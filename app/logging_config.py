import logging
import logging.config


def configure_logging(level: str = "INFO") -> None:
    """Single place that wires root logging; called once from the app lifespan.

    Console text format is deliberate for local development; structured JSON
    logging belongs to the deployment milestone, not day one.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-8s %(name)s %(message)s",
                },
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "default"},
            },
            "root": {"handlers": ["console"], "level": level.upper()},
        }
    )
