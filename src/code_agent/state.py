"""Shared workflow state passed between nodes.

``WorkflowState`` is the single object every node reads and mutates. It is
fully JSON-serialisable so project 2 can checkpoint and resume a workflow.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

from code_agent.message import AgentMessage
from code_agent.report import Finding, ReviewReport, UsageStats

Status = Literal["pending", "running", "done", "failed"]


class ReviewTask(BaseModel):
    target: Path
    glob: str = "**/*.py"
    max_files: int = 20
    focus: str | None = None
    out: Path | None = None


class TraceEvent(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    node: str
    event: str
    ok: bool = True
    dur_ms: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(BaseModel):
    run_id: str
    task: ReviewTask
    status: Status = "pending"
    node: str | None = None
    files: list[str] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    report: ReviewReport | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)
    usage: UsageStats = Field(default_factory=UsageStats)
    trace: list[TraceEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    # Live subscription for the trace; never serialised (see set_event_sink).
    _event_sink: Callable[[TraceEvent], None] | None = PrivateAttr(default=None)

    def set_event_sink(self, sink: Callable[[TraceEvent], None] | None) -> None:
        """Subscribe to trace events as they happen (used by the web stream)."""
        self._event_sink = sink

    def emit(self, event: TraceEvent) -> None:
        """Append an event to the trace and notify the subscriber, if any."""
        self.trace.append(event)
        if self._event_sink is not None:
            self._event_sink(event)
