"""Tests for ChatAgent (conversational mode) and the chat CLI command."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_agent import cli
from code_agent.agents.chat import REPLY_KEY, ChatAgent
from code_agent.config import AgentConfig
from code_agent.llm import LLMResult
from code_agent.message import AgentMessage, ToolCall
from code_agent.state import ReviewTask, WorkflowState
from code_agent.tools.builtin import build_default_registry
from fakes import FakeLLM

runner = CliRunner()


def _state(root: Path) -> WorkflowState:
    return WorkflowState(run_id="r1", task=ReviewTask(target=root))


def _agent(llm: FakeLLM, root: Path) -> ChatAgent:
    return ChatAgent(llm, build_default_registry(), AgentConfig(api_key="sk-test"), root)


async def test_tool_call_then_answer(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    llm = FakeLLM(
        [
            LLMResult(
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(target)})]
            ),
            LLMResult(content="该文件只有一行赋值。"),
        ]
    )

    state = await _agent(llm, tmp_path).run(_state(tmp_path))

    assert state.status == "done"
    assert state.artifacts[REPLY_KEY] == "该文件只有一行赋值。"
    assert state.usage.tool_calls == 1


async def test_conversational_mode_does_not_nudge(tmp_path: Path) -> None:
    llm = FakeLLM([LLMResult(content="直接回答")])
    state = _state(tmp_path)
    state.messages.append(AgentMessage(id="u1", role="user", content="问题"))

    state = await _agent(llm, tmp_path).run(state)

    nudges = [m for m in state.messages if "submit_review" in (m.content or "")]
    assert nudges == []
    assert state.artifacts[REPLY_KEY] == "直接回答"


async def test_multi_turn_memory_and_per_turn_usage(tmp_path: Path) -> None:
    llm = FakeLLM([LLMResult(content="答一"), LLMResult(content="答二")])
    agent = _agent(llm, tmp_path)
    state = _state(tmp_path)

    state.messages.append(AgentMessage(id="u1", role="user", content="问一"))
    state = await agent.run(state)
    assert state.usage.llm_calls == 1

    state.messages.append(AgentMessage(id="u2", role="user", content="问二"))
    state = await agent.run(state)

    # Budget window resets each turn, so usage does not accumulate forever.
    assert state.usage.llm_calls == 1
    # But the conversation itself is carried across turns.
    second_request = "\n".join(m.content or "" for m in llm.requests[1])
    assert "问一" in second_request
    assert "答一" in second_request
    assert "问二" in second_request


@pytest.fixture(autouse=True)
def _no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _patch_llm(monkeypatch: pytest.MonkeyPatch, fake: FakeLLM) -> None:
    monkeypatch.setattr(cli, "OpenAILLMClient", lambda _config: fake)


def test_chat_command_replies_and_exits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, FakeLLM([LLMResult(content="你好，我是代码助手。")]))

    result = runner.invoke(cli.app, ["chat", "--path", str(tmp_path)], input="hello\nexit\n")

    assert result.exit_code == 0
    assert "你好" in result.stdout


def test_chat_command_carries_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeLLM([LLMResult(content="答一"), LLMResult(content="答二")])
    _patch_llm(monkeypatch, fake)

    result = runner.invoke(cli.app, ["chat", "--path", str(tmp_path)], input="问一\n问二\nexit\n")

    assert result.exit_code == 0
    assert len(fake.requests) == 2
    second_request = "\n".join(m.content or "" for m in fake.requests[1])
    assert "问一" in second_request and "答一" in second_request


def test_chat_command_eof_exits_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_llm(monkeypatch, FakeLLM([LLMResult(content="unused")]))

    result = runner.invoke(cli.app, ["chat", "--path", str(tmp_path)], input="")

    assert result.exit_code == 0


def test_chat_command_missing_key_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["chat", "--path", str(tmp_path)])
    assert result.exit_code == 2


def test_chat_command_listed_in_help() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "chat" in result.stdout
