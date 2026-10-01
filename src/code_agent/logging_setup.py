"""Structured ``key=value`` logging to stderr.

Format (DESIGN.md section 10)::

    ts=<utc> level=INFO logger=code_agent.runner msg=... run=8f3a iter=2 dur_ms=12

Values passed via the ``kv`` extra are rendered after the message::

    logger.info("tool call", extra={"kv": {"tool": "read_file", "ok": True}})
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from typing import IO, Any

LOGGER_NAME = "code_agent"

_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def _fmt_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"' if (" " in value or not value) else value
    return str(value)


class KvFormatter(logging.Formatter):
    """Render a record as a single ``key=value`` line."""

    def format(self, record: logging.LogRecord) -> str:
        moment = datetime.fromtimestamp(record.created, tz=UTC)
        ts = moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(record.msecs):03d}Z"
        parts = [
            f"ts={ts}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg={_fmt_value(record.getMessage())}",
        ]
        kv = getattr(record, "kv", None)
        if isinstance(kv, dict):
            parts.extend(f"{key}={_fmt_value(value)}" for key, value in kv.items())
        if record.exc_info:
            parts.append(f"exc={_fmt_value(self.formatException(record.exc_info))}")
        return " ".join(parts)


def setup_logging(level: int | str = logging.INFO, stream: IO[str] | None = None) -> logging.Logger:
    """Configure and return the ``code_agent`` logger."""
    if isinstance(level, str):
        level = _LEVELS.get(level.upper(), logging.INFO)

    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(KvFormatter())

    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger under the ``code_agent`` namespace."""
    if not name:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
