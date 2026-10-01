"""Tests for the BaseAgent tool-calling loop, driven by a scripted FakeLLM."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from code_agent.base_agent import BaseAgent
from code_agent.config import AgentConfig
from code_agent.llm import LLMResult
from code_agent.message import ToolCall
from code_agent.report import ReviewReport
from code_agent.state import ReviewTask, WorkflowState
from code_agent.tools.registry import Tool, ToolRegistry
from fakes import FakeLLM


class DummyAgent(BaseAgent):
    name = "DummyAgent"
    system_prompt = "you are a reviewer"
    finish_tool = "submit_review"

    async def _finalize(self, state: WorkflowState, arguments: dict[str, Any]) -> WorkflowState:
        state.report = ReviewReport.model_validate(
            {**arguments, "score": arguments.get("score", 0)}
        )
        state.status = "done"
        return state


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                name="read_file",
                description="read",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                func=lambda path: {"ok": True, "path": path, "content": "x = 1"},
            ),
            Tool(
                name="submit_review",
                description="submit",
                parameters={"type": "object", "properties": {}},
                func=lambda **_: {"ok": True},
            ),
        ]
    )


def _state(**kwargs: Any) -> WorkflowState:
    return WorkflowState(run_id="r1", task=ReviewTask(target=Path("x.py")), **kwargs)


def _tool_result(call_id: str, name: str, args: dict[str, Any] | None = None) -> LLMResult:
    return LLMResult(tool_calls=[ToolCall(id=call_id, name=name, arguments=args or {})])


def _agent(llm: FakeLLM, **config: Any) -> DummyAgent:
    return DummyAgent(llm, _registry(), AgentConfig(api_key="sk-test", **config))


async def test_tool_call_then_submit_produces_report() -> None:
    llm = FakeLLM(
        [
            _tool_result("c1", "read_file", {"path": "x.py"}),
            _tool_result("c2", "submit_review", {"summary": "ok", "score": 90}),
        ]
    )
    state = await _agent(llm).run(_state())

    assert state.status == "done"
    assert state.report is not None and state.report.score == 90
    assert state.usage.tool_calls == 1
    tool_messages = [m for m in state.messages if m.role == "tool"]
    assert json.loads(tool_messages[0].content or "{}")["ok"] is True


async def test_system_prompt_seeded_once() -> None:
    llm = FakeLLM([_tool_result("c1", "submit_review", {"summary": "s", "score": 10})])
    state = await _agent(llm).run(_state())
    systems = [m for m in state.messages if m.role == "system"]
    assert len(systems) == 1
    assert systems[0].content == "you are a reviewer"


async def test_nudge_when_model_answers_without_tools() -> None:
    llm = FakeLLM(
        [
            LLMResult(content="here is my answer"),
            _tool_result("c1", "submit_review", {"summary": "s", "score": 50}),
        ]
    )
    state = await _agent(llm).run(_state())
    assert state.status == "done"
    nudges = [
        m for m in state.messages if m.role == "user" and "submit_review" in (m.content or "")
    ]
    assert len(nudges) == 1


async def test_second_tool_free_answer_ends_the_loop() -> None:
    llm = FakeLLM([LLMResult(content="a"), LLMResult(content="b")])
    state = await _agent(llm).run(_state())
    assert state.status == "failed"
    assert any("max_iterations" in w for w in state.warnings)


async def test_invalid_terminal_args_are_repaired() -> None:
    llm = FakeLLM(
        [
            _tool_result("c1", "submit_review", {"summary": "bad", "score": 999}),
            _tool_result("c2", "submit_review", {"summary": "good", "score": 80}),
        ]
    )
    state = await _agent(llm).run(_state())
    assert state.status == "done"
    assert state.report is not None and state.report.score == 80
    assert any(e.event == "repair" for e in state.trace)


async def test_repairs_give_up_after_max_repairs() -> None:
    bad = {"summary": "bad", "score": 999}
    llm = FakeLLM(
        [
            _tool_result("c1", "submit_review", bad),
            _tool_result("c2", "submit_review", bad),
            _tool_result("c3", "submit_review", bad),
        ]
    )
    state = await _agent(llm, max_repairs=1).run(_state())
    assert state.status == "failed"
    assert any("invalid_report" in w for w in state.warnings)


async def test_token_budget_trips_before_first_call() -> None:
    llm = FakeLLM([])
    state = _state()
    state.usage.prompt_tokens = 10**6
    state = await _agent(llm).run(state)
    assert state.status == "failed"
    assert llm.requests == []
    assert any("token_budget" in w for w in state.warnings)


async def test_max_iterations_guard() -> None:
    llm = FakeLLM([_tool_result("c1", "read_file", {"path": "x.py"})])
    state = await _agent(llm, max_iterations=1).run(_state())
    assert state.status == "failed"
    assert any("max_iterations" in w for w in state.warnings)
