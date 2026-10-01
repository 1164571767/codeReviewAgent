"""Reviewer agent: runs the tool-calling loop and produces a ReviewReport."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from code_agent.base_agent import BaseAgent
from code_agent.config import AgentConfig
from code_agent.llm import LLMClient
from code_agent.memory import JSONMemory
from code_agent.prompts import REVIEWER_SYSTEM_PROMPT
from code_agent.report import Finding, ReviewReport
from code_agent.state import WorkflowState
from code_agent.tools.registry import Tool, ToolRegistry

SUBMIT_TOOL = "submit_review"


def _extract_findings(raw: Any) -> list[Finding]:
    """Salvage any individually valid findings from a rejected submission."""
    if not isinstance(raw, list):
        return []
    findings: list[Finding] = []
    for item in raw:
        try:
            findings.append(Finding.model_validate(item))
        except ValidationError:
            continue
    return findings


def _submit_tool() -> Tool:
    return Tool(
        name=SUBMIT_TOOL,
        description="Submit the final structured code review report.",
        parameters=ReviewReport.submission_schema(),
        func=lambda **_: {"ok": True},
    )


class ReviewerAgent(BaseAgent):
    name = "ReviewerAgent"
    system_prompt = REVIEWER_SYSTEM_PROMPT
    finish_tool = SUBMIT_TOOL

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        config: AgentConfig,
        memory: JSONMemory | None = None,
    ) -> None:
        if SUBMIT_TOOL not in tools:
            tools.register(_submit_tool())
        super().__init__(llm, tools, config, memory)

    async def _finalize(self, state: WorkflowState, arguments: dict[str, Any]) -> WorkflowState:
        salvaged = _extract_findings(arguments.get("findings"))
        if salvaged:
            state.findings = salvaged

        report = ReviewReport.model_validate(arguments)
        report.generated_at = datetime.now(UTC)
        report.model = self._config.model
        report.usage = state.usage.model_copy()
        if not report.files_reviewed:
            report.files_reviewed = list(state.files)

        state.report = report
        state.findings = list(report.findings)
        state.status = "done"
        return state

    async def _degrade(self, state: WorkflowState, reason: str) -> WorkflowState:
        if state.report is None and state.findings:
            state.report = ReviewReport(
                summary=f"仅得到部分结果（{reason}）。",
                score=0,
                files_reviewed=list(state.files),
                findings=list(state.findings),
                model=self._config.model,
                usage=state.usage.model_copy(),
            )
        return await super()._degrade(state, reason)
