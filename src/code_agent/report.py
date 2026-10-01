"""Structured review report schema.

``UsageStats`` lives here (rather than in ``state.py``) so that
``state.py`` can import from this module without a circular import.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, Field


class Severity(StrEnum):
    info = "info"
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class UsageStats(BaseModel):
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Finding(BaseModel):
    id: str
    severity: Severity
    category: str
    file: str
    line: int | None = None
    title: str
    detail: str
    suggestion: str | None = None
    evidence: str | None = None


class ReviewReport(BaseModel):
    summary: str
    score: int = Field(ge=0, le=100)
    files_reviewed: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model: str = ""
    usage: UsageStats = Field(default_factory=UsageStats)

    # Filled in by the runner, never by the model.
    RUNTIME_FIELDS: ClassVar[tuple[str, ...]] = ("generated_at", "model", "usage")

    @classmethod
    def submission_schema(cls) -> dict[str, Any]:
        """JSON schema for the ``submit_review`` tool input.

        Runtime fields the model must not supply are stripped from both
        ``properties`` and ``required``.
        """
        schema = cls.model_json_schema()
        for field in cls.RUNTIME_FIELDS:
            schema.get("properties", {}).pop(field, None)
        if "required" in schema:
            schema["required"] = [n for n in schema["required"] if n not in cls.RUNTIME_FIELDS]
        return schema

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2)
