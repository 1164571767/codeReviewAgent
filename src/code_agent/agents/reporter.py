"""Reporter node: render the final report to Markdown."""

from __future__ import annotations

from code_agent.logging_setup import get_logger
from code_agent.report import render_markdown
from code_agent.state import WorkflowState

log = get_logger("reporter")


class ReporterNode:
    name = "Reporter"

    async def run(self, state: WorkflowState) -> WorkflowState:
        if state.report is None:
            state.status = "failed"
            state.error = state.error or "no report was produced"
            return state

        state.artifacts["markdown"] = render_markdown(state.report)
        state.status = "done"
        log.info("report ready", extra={"kv": {"findings": len(state.report.findings)}})
        return state
