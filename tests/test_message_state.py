"""Tests for messages and shared workflow state."""

from __future__ import annotations

from pathlib import Path

from code_agent.message import AgentMessage, ToolCall
from code_agent.report import ReviewReport
from code_agent.state import ReviewTask, TraceEvent, WorkflowState


def test_tool_message_to_openai_keeps_tool_call_id() -> None:
    msg = AgentMessage(id="m1", role="tool", tool_call_id="c1", name="read_file", content="{}")
    payload = msg.to_openai()
    assert payload == {"role": "tool", "content": "{}", "tool_call_id": "c1"}


def test_assistant_message_serialises_tool_calls() -> None:
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})
    msg = AgentMessage(id="m2", role="assistant", tool_calls=[call])
    payload = msg.to_openai()
    assert payload["role"] == "assistant"
    assert "content" not in payload
    assert payload["tool_calls"][0]["function"] == {
        "name": "read_file",
        "arguments": '{"path": "a.py"}',
    }


def test_to_openai_drops_internal_fields() -> None:
    msg = AgentMessage(id="m3", role="user", content="hi", meta={"tokens": 3})
    assert "meta" not in msg.to_openai()
    assert "id" not in msg.to_openai()
    assert "created_at" not in msg.to_openai()


def test_usage_stats_defaults_independent() -> None:
    a = WorkflowState(run_id="r1", task=ReviewTask(target=Path(".")))
    b = WorkflowState(run_id="r2", task=ReviewTask(target=Path(".")))
    a.usage.llm_calls += 1
    assert b.usage.llm_calls == 0


def test_state_json_round_trip() -> None:
    state = WorkflowState(run_id="r1", task=ReviewTask(target=Path("x.py"), glob="*.py"))
    state.files.append("x.py")
    event = TraceEvent(node="ReviewerAgent", event="tool_call", data={"tool": "read_file"})
    state.trace.append(event)
    state.report = ReviewReport(summary="s", score=50)
    restored = WorkflowState.model_validate_json(state.model_dump_json())
    assert restored.files == ["x.py"]
    assert restored.trace[0].data["tool"] == "read_file"
    assert restored.report is not None and restored.report.score == 50
