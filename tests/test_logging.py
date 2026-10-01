"""Tests for the key=value log formatter."""

from __future__ import annotations

import io
import logging

from code_agent.logging_setup import KvFormatter, setup_logging


def _record(**kv: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="code_agent.runner",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="tool call",
        args=(),
        exc_info=None,
    )
    record.kv = kv
    return record


def test_format_contains_base_fields() -> None:
    line = KvFormatter().format(_record())
    assert line.startswith("ts=")
    assert "level=INFO" in line
    assert "logger=code_agent.runner" in line
    assert 'msg="tool call"' in line


def test_format_renders_kv_values() -> None:
    line = KvFormatter().format(_record(tool="read_file", ok=True, dur_ms=12))
    assert "tool=read_file" in line
    assert "ok=true" in line
    assert "dur_ms=12" in line


def test_format_quotes_strings_with_spaces() -> None:
    line = KvFormatter().format(_record(error="file not found"))
    assert 'error="file not found"' in line


def test_setup_logging_writes_to_stream() -> None:
    stream = io.StringIO()
    logger = setup_logging("DEBUG", stream=stream)
    logger.info("ready")
    output = stream.getvalue()
    assert output.startswith("ts=")
    assert 'msg=ready' in output
    assert logger.name == "code_agent"
