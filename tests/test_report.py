"""Tests for the review report schema."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from code_agent.report import Finding, ReviewReport, Severity, UsageStats


def _finding(**overrides: object) -> Finding:
    data: dict[str, object] = {
        "id": "F-001",
        "severity": Severity.high,
        "category": "security",
        "file": "a.py",
        "line": 3,
        "title": "SQL injection",
        "detail": "Query built with % formatting.",
    }
    data.update(overrides)
    return Finding(**data)  # type: ignore[arg-type]


def test_severity_from_string() -> None:
    assert _finding(severity="low").severity is Severity.low


def test_severity_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        _finding(severity="blocker")


def test_score_bounds() -> None:
    ReviewReport(summary="ok", score=0)
    ReviewReport(summary="ok", score=100)
    with pytest.raises(ValidationError):
        ReviewReport(summary="ok", score=101)


def test_round_trip_json() -> None:
    report = ReviewReport(summary="s", score=80, findings=[_finding()])
    restored = ReviewReport.model_validate(json.loads(report.to_json()))
    assert restored.findings[0].severity is Severity.high
    assert restored.usage.llm_calls == 0


def test_total_tokens() -> None:
    assert UsageStats(prompt_tokens=10, completion_tokens=5).total_tokens == 15


def test_submission_schema_strips_runtime_fields() -> None:
    schema = ReviewReport.submission_schema()
    props = schema["properties"]
    assert "summary" in props
    assert "score" in props
    assert "findings" in props
    for field in ("generated_at", "model", "usage"):
        assert field not in props
        assert field not in schema.get("required", [])
