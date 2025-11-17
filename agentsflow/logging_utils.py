"""Central logging helpers for AgentsFlow entry points."""

from __future__ import annotations

import logging
import os
from typing import Any

LOG_LEVEL_ENV = "AGENTSFLOW_LOG_LEVEL"
DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DEFAULT_NUMERIC_LEVEL = getattr(logging, DEFAULT_LOG_LEVEL, logging.INFO)

_logger = logging.getLogger(__name__)


def _normalize_log_level(value: Any) -> int:
    if value is None:
        return _DEFAULT_NUMERIC_LEVEL
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return _DEFAULT_NUMERIC_LEVEL
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        try:
            return int(text)
        except ValueError:  # pragma: no cover - defensive guard
            pass
    candidate = getattr(logging, text.upper(), None)
    if isinstance(candidate, int):
        return candidate
    _logger.warning(
        "Invalid log level '%s'; defaulting to %s.", text, DEFAULT_LOG_LEVEL
    )
    return _DEFAULT_NUMERIC_LEVEL


def configure_logging(level: str | int | None = None) -> int:
    """Configure the root logger once using our preferred format."""

    raw_level = level if level is not None else os.getenv(LOG_LEVEL_ENV)
    numeric_level = _normalize_log_level(raw_level)
    logging.basicConfig(level=numeric_level, format=LOG_FORMAT, force=True)
    logging.captureWarnings(True)
    _logger.debug(
        "Logging configured.",
        extra={
            "level": logging.getLevelName(numeric_level),
            "env": LOG_LEVEL_ENV,
            "raw_level": raw_level or DEFAULT_LOG_LEVEL,
        },
    )
    return numeric_level


__all__ = [
    "LOG_LEVEL_ENV",
    "DEFAULT_LOG_LEVEL",
    "configure_logging",
]
