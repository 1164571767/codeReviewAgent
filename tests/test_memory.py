"""Tests for JSONMemory and context trimming."""

from __future__ import annotations

from pathlib import Path

from code_agent.memory import JSONMemory, estimate_tokens
from code_agent.message import AgentMessage, ToolCall
from code_agent.report import ReviewReport
from code_agent.state import ReviewTask, WorkflowState


def _state(messages: list[AgentMessage] | None = None) -> WorkflowState:
    state = WorkflowState(run_id="run-1", task=ReviewTask(target=Path("x.py")))
    if messages:
        state.messages.extend(messages)
    return state


def _user(text: str, mid: str) -> AgentMessage:
    return AgentMessage(id=mid, role="user", content=text)


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    memory = JSONMemory(root=tmp_path)
    state = _state([_user("hello", "m1")])
    state.report = ReviewReport(summary="s", score=42)
    path = memory.save(state)
    assert path.exists()
    restored = memory.load("run-1")
    assert restored.messages[0].content == "hello"
    assert restored.report is not None and restored.report.score == 42


def test_build_context_returns_copy_when_small() -> None:
    memory = JSONMemory(token_budget=10_000)
    messages = [_user("a", "m1"), _user("b", "m2")]
    context = memory.build_context(_state(messages))
    assert [m.id for m in context] == ["m1", "m2"]
    assert context is not memory


def test_build_context_keeps_system_and_newest() -> None:
    memory = JSONMemory(token_budget=30)
    messages = [
        AgentMessage(id="s1", role="system", content="rules"),
        _user("x" * 400, "u1"),
        _user("tail", "u2"),
    ]
    context = memory.build_context(_state(messages))
    assert context[0].role == "system"
    assert context[-1].id == "u2"
    assert len(context) < len(messages)


def test_build_context_does_not_start_with_orphan_tool() -> None:
    memory = JSONMemory(token_budget=20)
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    messages = [
        AgentMessage(id="s1", role="system", content="rules"),
        AgentMessage(id="a1", role="assistant", tool_calls=[call]),
        AgentMessage(id="t1", role="tool", tool_call_id="c1", name="read_file", content="x" * 400),
        _user("nudge", "u1"),
    ]
    context = memory.build_context(_state(messages))
    assert context[0].role == "system"
    assert context[1].role != "tool"


def test_build_context_keeps_call_with_its_result() -> None:
    memory = JSONMemory(token_budget=200)
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    messages = [
        AgentMessage(id="s1", role="system", content="rules"),
        AgentMessage(id="a1", role="assistant", tool_calls=[call]),
        AgentMessage(id="t1", role="tool", tool_call_id="c1", name="read_file", content="body"),
    ]
    context = memory.build_context(_state(messages))
    roles = [m.role for m in context]
    assert roles == ["system", "assistant", "tool"]


def test_estimate_scales_with_content() -> None:
    small = estimate_tokens([_user("hi", "m1")])
    large = estimate_tokens([_user("x" * 4000, "m1")])
    assert large > small
