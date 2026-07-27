"""Structured JSON logging configuration."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog


def _drop_color_message(
    _: logging.Logger, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Remove Uvicorn's terminal-only duplicate message field."""
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging(level: str) -> None:
    """Route application and server logs through one JSON renderer."""
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _drop_color_message,
    ]
    renderer = structlog.processors.JSONRenderer(sort_keys=True)
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return the application logger without capturing configuration state."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger())
