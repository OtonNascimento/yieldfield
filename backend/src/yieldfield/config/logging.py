"""Structured logging bootstrap (§11 observability).

Configured once at boot from `Settings`. Console renderer locally for readability,
JSON renderer everywhere else so logs are machine-parseable in staging/production.
Both the API and the workers call `configure_logging()` so they share one format.
"""

from __future__ import annotations

import logging
from typing import cast

import structlog

from yieldfield.config.settings import Settings


def configure_logging(settings: Settings) -> None:
    """Initialise structlog + stdlib logging from validated settings."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level),
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
