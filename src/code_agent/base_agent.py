"""Base agent: the tool-calling loop shared by every agent (DESIGN.md section 8).

``BaseAgent`` implements the ``Node`` protocol structurally (``name`` +
``async run(state)``) without importing it, so nodes stay decoupled.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import ValidationError

from code_agent.config import AgentConfig
from code_agent.errors import ReviewError
from code_agent.llm import LLMClient
from code_agent.logging_setup import get_logger
from code_agent.memory import JSONMemory
from code_agent.message import AgentMessage, ToolCall
from code_agent.state import TraceEvent, WorkflowState
from code_agent.tools.registry import ToolRegistry

log = get_logger("agent")


def new_id() -> str:
    return uuid4().hex[:12]


class BaseAgent:
    """Two modes, selected by ``finish_tool``:

    * **terminal mode** (``finish_tool`` set, e.g. ``submit_review``): the loop
      runs until that tool is called; ``_finalize`` validates its arguments.
    * **conversational mode** (``finish_tool is None``): a plain assistant
      answer ends the turn and is stored in ``state.artifacts["reply"]``.
    """

    name: ClassVar[str] = "BaseAgent"
    system_prompt: str = ""
    finish_tool: ClassVar[str | None] = None

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        config: AgentConfig,
        memory: JSONMemory | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._config = config
        self._memory = memory or JSONMemory(token_budget=config.token_budget)

    async def run(self, state: WorkflowState) -> WorkflowState:
        self._seed_system(state)
        state.status = "running"
        nudged = False
        repairs = 0

        for _ in range(self._config.max_iterations):
            if state.usage.total_tokens >= self._config.token_budget:
                state.warnings.append("token budget exceeded")
                return await self._degrade(state, "token_budget")

            message = await self._step(state)
            state.messages.append(message)
            log.info(
                "llm turn",
                extra={"kv": {"node": self.name, "tool_calls": len(message.tool_calls)}},
            )

            if message.tool_calls:
                terminal = self._terminal_call(message)
                if terminal is not None:
                    try:
                        return await self._finalize(state, terminal.arguments)
                    except (ValidationError, ReviewError) as exc:
                        repairs += 1
                        state.emit(
                            TraceEvent(
                                node=self.name,
                                event="repair",
                                ok=False,
                                data={"error": str(exc)},
                            )
                        )
                        if repairs > self._config.max_repairs:
                            state.warnings.append(f"terminal report rejected: {exc}")
                            return await self._degrade(state, "invalid_report")
                        state.messages.append(self._repair_message(exc))
                        continue
                state.messages.extend(await self._execute_tools(state, message.tool_calls))
                continue

            # The model answered without calling a tool.
            if self.finish_tool is None:
                # Conversational mode: prose is the answer, the turn is over.
                state.artifacts["reply"] = message.content or ""
                state.status = "done"
                return state
            if nudged:
                break
            nudged = True
            state.messages.append(self._nudge_message())

        state.warnings.append("max iterations reached")
        return await self._degrade(state, "max_iterations")

    async def _step(self, state: WorkflowState) -> AgentMessage:
        context = self._memory.build_context(state)
        result = await self._llm.chat(context, tools=self._tools.schemas())
        state.usage.llm_calls += 1
        state.usage.prompt_tokens += result.prompt_tokens
        state.usage.completion_tokens += result.completion_tokens
        state.emit(
            TraceEvent(
                node=self.name,
                event="llm_response",
                data={"tool_calls": len(result.tool_calls)},
            )
        )
        return AgentMessage(
            id=new_id(),
            role="assistant",
            content=result.content,
            tool_calls=result.tool_calls,
            meta={"model": result.model},
        )

    async def _execute_tools(
        self,
        state: WorkflowState,
        calls: list[ToolCall],
    ) -> list[AgentMessage]:
        for call in calls:
            state.emit(
                TraceEvent(node=self.name, event="tool_call", data={"tool": call.name})
            )
        outcomes = await asyncio.gather(*(self._timed_call(call) for call in calls))
        messages: list[AgentMessage] = []
        for call, (outcome, dur_ms) in zip(calls, outcomes, strict=True):
            ok = bool(outcome.get("ok"))
            state.usage.tool_calls += 1
            state.emit(
                TraceEvent(
                    node=self.name,
                    event="tool_result",
                    ok=ok,
                    dur_ms=dur_ms,
                    data={"tool": call.name},
                )
            )
            log.info("tool result", extra={"kv": {"tool": call.name, "ok": ok, "dur_ms": dur_ms}})
            messages.append(
                AgentMessage(
                    id=new_id(),
                    role="tool",
                    tool_call_id=call.id,
                    name=call.name,
                    content=json.dumps(outcome, ensure_ascii=False),
                )
            )
        return messages

    async def _timed_call(self, call: ToolCall) -> tuple[dict[str, Any], int]:
        start = time.perf_counter()
        outcome = await asyncio.to_thread(self._tools.call, call.name, call.arguments)
        return outcome, int((time.perf_counter() - start) * 1000)

    def _terminal_call(self, message: AgentMessage) -> ToolCall | None:
        if not self.finish_tool:
            return None
        for call in message.tool_calls:
            if call.name == self.finish_tool:
                return call
        return None

    def _seed_system(self, state: WorkflowState) -> None:
        if self.system_prompt and not any(m.role == "system" for m in state.messages):
            state.messages.insert(
                0, AgentMessage(id=new_id(), role="system", content=self.system_prompt)
            )

    def _nudge_message(self) -> AgentMessage:
        target = self.finish_tool or "the required tool"
        return AgentMessage(
            id=new_id(),
            role="user",
            content=f"请调用 {target} 提交结构化结果。",
        )

    def _repair_message(self, exc: Exception) -> AgentMessage:
        return AgentMessage(
            id=new_id(),
            role="user",
            content=f"上一次提交不符合 schema（{exc}）。请修正后重新调用 {self.finish_tool}。",
        )

    async def _degrade(self, state: WorkflowState, reason: str) -> WorkflowState:
        state.warnings.append(f"agent degraded: {reason}")
        if state.report is None:
            state.status = "failed"
            state.error = state.error or f"agent degraded: {reason}"
        else:
            state.status = "done"
        return state

    async def _finalize(self, state: WorkflowState, arguments: dict[str, Any]) -> WorkflowState:
        """Validate terminal tool arguments into ``state`` and finish.

        Only reached in terminal mode; any subclass that sets ``finish_tool``
        must override this.
        """
        raise NotImplementedError(f"{self.name} sets finish_tool but not _finalize")
