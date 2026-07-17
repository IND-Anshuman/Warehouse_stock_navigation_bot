"""
Structured logging module using structlog.
Provides consistent, JSON-formatted log output across all services.
"""
import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def _add_service_info(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """Add service metadata to every log entry."""
    from app.config import settings  # noqa: imported at call time to avoid circular imports
    event_dict["service"] = settings.SERVICE_NAME
    return event_dict


def _drop_color_message_key(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """Remove uvicorn's color_message from log entries."""
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging(log_level: str = "INFO", json_logs: bool = True) -> None:
    """
    Configure structlog for the entire application.
    
    In production (json_logs=True): outputs structured JSON.
    In development (json_logs=False): outputs colorized human-readable text.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.ExtraAdder(),
        _drop_color_message_key,
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        # Production: structured JSON
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.make_filtering_bound_logger(
                logging.getLevelName(log_level.upper())
            ),
            cache_logger_on_first_use=True,
        )
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    else:
        # Development: colored console output
        structlog.configure(
            processors=[
                *shared_processors,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.make_filtering_bound_logger(
                logging.getLevelName(log_level.upper())
            ),
            cache_logger_on_first_use=True,
        )
        formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    # Silence noisy third-party loggers
    for noisy_logger in ["uvicorn", "uvicorn.error", "fastapi"]:
        logging.getLogger(noisy_logger).handlers = []
        logging.getLogger(noisy_logger).propagate = True

    logging.getLogger("uvicorn.access").handlers = []
    logging.getLogger("uvicorn.access").propagate = False


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Get a bound logger with the given name."""
    return structlog.get_logger(name)
