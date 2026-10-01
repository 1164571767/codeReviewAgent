"""Collector node: turn the task target into a concrete file list."""

from __future__ import annotations

from uuid import uuid4

from code_agent.logging_setup import get_logger
from code_agent.message import AgentMessage
from code_agent.prompts import build_review_prompt
from code_agent.state import WorkflowState

log = get_logger("collector")


class CollectorNode:
    name = "Collector"

    async def run(self, state: WorkflowState) -> WorkflowState:
        target = state.task.target
        if not target.exists():
            state.status = "failed"
            state.error = f"path not found: {target}"
            return state

        if target.is_file():
            files = [str(target)]
        else:
            files = sorted(
                str(path) for path in target.glob(state.task.glob) if path.is_file()
            )[: state.task.max_files]

        if not files:
            state.status = "failed"
            state.error = f"no files matched glob {state.task.glob!r} under {target}"
            return state

        state.files = files
        state.artifacts["files"] = list(files)
        state.messages.append(
            AgentMessage(
                id=uuid4().hex[:12],
                role="user",
                content=build_review_prompt(state.task, files),
            )
        )
        log.info("collected files", extra={"kv": {"count": len(files)}})
        return state
