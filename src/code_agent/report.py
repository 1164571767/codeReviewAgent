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


_SEVERITY_ORDER = {
    Severity.critical: 0,
    Severity.high: 1,
    Severity.medium: 2,
    Severity.low: 3,
    Severity.info: 4,
}


def render_markdown(report: ReviewReport) -> str:
    """Render a report as Markdown (summary table + per-finding detail)."""
    lines: list[str] = [
        "# 代码审查报告",
        "",
        report.summary,
        "",
        f"- 评分：{report.score}/100",
        f"- 模型：{report.model or 'n/a'}",
        f"- 审查文件：{len(report.files_reviewed)} 个",
        f"- 发现：{len(report.findings)} 条",
        "",
    ]

    if not report.findings:
        lines.append("未发现明显问题。")
        return "\n".join(lines)

    ordered = sorted(report.findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 9))

    lines.append("## 发现一览")
    lines.append("")
    lines.append("| 严重度 | 类别 | 位置 | 标题 |")
    lines.append("| --- | --- | --- | --- |")
    for finding in ordered:
        location = f"{finding.file}:{finding.line}" if finding.line else finding.file
        lines.append(
            f"| {finding.severity} | {finding.category} | {location} | {finding.title} |"
        )

    lines.append("")
    lines.append("## 详细")
    for finding in ordered:
        location = f"{finding.file}:{finding.line}" if finding.line else finding.file
        lines.append("")
        lines.append(f"### [{finding.severity}] {finding.title} — {location}")
        lines.append(finding.detail)
        if finding.suggestion:
            lines.append(f"\n**建议**：{finding.suggestion}")
        if finding.evidence:
            lines.append("\n```python")
            lines.append(finding.evidence)
            lines.append("```")
    return "\n".join(lines)
