"""Tests for the review CLI command (FakeLLM injected, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_agent import cli
from code_agent.llm import LLMResult
from code_agent.memory import JSONMemory
from code_agent.message import ToolCall
from fakes import FakeLLM

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "JSONMemory", lambda **kwargs: JSONMemory(root=tmp_path, **kwargs))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def _submit() -> LLMResult:
    call = ToolCall(
        id="c1",
        name="submit_review",
        arguments={"summary": "看起来不错", "score": 88},
    )
    return LLMResult(tool_calls=[call])


def _patch_llm(monkeypatch: pytest.MonkeyPatch, fake: FakeLLM) -> None:
    monkeypatch.setattr(cli, "OpenAILLMClient", lambda _config: fake)


def test_help_lists_review_command() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "review" in result.stdout


def test_review_writes_report_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    out = tmp_path / "report.md"
    _patch_llm(monkeypatch, FakeLLM([_submit()]))

    result = runner.invoke(cli.app, ["review", str(target), "--out", str(out)])

    assert result.exit_code == 0
    assert out.exists()
    assert "# 代码审查报告" in out.read_text(encoding="utf-8")


def test_review_prints_markdown_to_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    _patch_llm(monkeypatch, FakeLLM([_submit()]))

    result = runner.invoke(cli.app, ["review", str(target)])

    assert result.exit_code == 0
    assert "代码审查报告" in result.stdout


def test_missing_api_key_exits_2(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["review", str(target)])
    assert result.exit_code == 2


def test_missing_path_exits_2(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["review", str(tmp_path / "nope.py")])
    assert result.exit_code == 2


def test_verbose_and_quiet_conflict_exits_2(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["review", str(target), "-v", "-q"])
    assert result.exit_code == 2


def test_no_report_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")
    # Model answers with prose twice: no submit_review, loop degrades to failed.
    _patch_llm(monkeypatch, FakeLLM([LLMResult(content="a"), LLMResult(content="b")]))

    result = runner.invoke(cli.app, ["review", str(target)])

    assert result.exit_code == 1
