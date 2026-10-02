"""Tests for the web layer.

Consumes the SSE async generator directly instead of going through
``TestClient``, so no ``httpx`` dependency is needed.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

pytest.importorskip("fastapi")

from code_agent import cli  # noqa: E402
from code_agent.config import AgentConfig  # noqa: E402
from code_agent.llm import LLMResult  # noqa: E402
from code_agent.message import ToolCall  # noqa: E402
from code_agent.web.app import STATIC_DIR, ReviewRequest, create_app, stream_review  # noqa: E402
from fakes import FakeLLM  # noqa: E402

runner = CliRunner()


async def _collect(stream: AsyncIterator[str]) -> list[dict]:
    frames: list[dict] = []
    async for chunk in stream:
        for line in chunk.splitlines():
            if line.startswith("data: "):
                frames.append(json.loads(line[6:]))
    return frames


def _scripted_llm() -> FakeLLM:
    return FakeLLM(
        [
            LLMResult(
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})]
            ),
            LLMResult(
                tool_calls=[
                    ToolCall(
                        id="c2",
                        name="submit_review",
                        arguments={
                            "summary": "有一处安全问题。",
                            "score": 70,
                            "findings": [
                                {
                                    "id": "F-001",
                                    "severity": "high",
                                    "category": "security",
                                    "file": "a.py",
                                    "line": 1,
                                    "title": "SQL 注入",
                                    "detail": "字符串拼接。",
                                }
                            ],
                        },
                    )
                ]
            ),
        ]
    )


async def test_stream_emits_start_trace_done(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("import os\n", encoding="utf-8")
    fake = _scripted_llm()

    frames = await _collect(
        stream_review(
            ReviewRequest(path=str(target)),
            AgentConfig(api_key="sk-test"),
            llm_factory=lambda _config: fake,
        )
    )

    assert frames[0]["type"] == "start"
    kinds = [f["type"] for f in frames]
    assert "trace" in kinds
    assert kinds[-1] == "done"

    events = [f["event"]["event"] for f in frames if f["type"] == "trace"]
    assert "node_start" in events
    assert "tool_call" in events
    assert "node_end" in events

    done = frames[-1]
    assert done["status"] == "done"
    assert done["report"]["score"] == 70
    assert "# 代码审查报告" in done["markdown"]


async def test_trace_carries_tool_timing(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    frames = await _collect(
        stream_review(
            ReviewRequest(path=str(target)),
            AgentConfig(api_key="sk-test"),
            llm_factory=lambda _config: _scripted_llm(),
        )
    )

    results = [
        f["event"] for f in frames if f["type"] == "trace" and f["event"]["event"] == "tool_result"
    ]
    assert results
    assert isinstance(results[0]["dur_ms"], int)


async def test_stream_reports_failure(tmp_path: Path) -> None:
    target = tmp_path / "a.py"
    target.write_text("x = 1\n", encoding="utf-8")

    def boom(_config: AgentConfig) -> FakeLLM:
        raise RuntimeError("no llm for you")

    frames = await _collect(
        stream_review(
            ReviewRequest(path=str(target)),
            AgentConfig(api_key="sk-test"),
            llm_factory=boom,
        )
    )

    assert frames[-1]["type"] == "error"
    assert "no llm for you" in frames[-1]["message"]


async def test_missing_path_reports_failed_run(tmp_path: Path) -> None:
    frames = await _collect(
        stream_review(
            ReviewRequest(path=str(tmp_path / "nope.py")),
            AgentConfig(api_key="sk-test"),
            llm_factory=lambda _config: _scripted_llm(),
        )
    )

    done = frames[-1]
    assert done["type"] == "done"
    assert done["status"] == "failed"
    assert "path not found" in (done["error"] or "")


def test_create_app_registers_routes() -> None:
    paths = {route.path for route in create_app().routes}
    assert {"/", "/api/config", "/api/review"} <= paths


def test_static_assets_shipped() -> None:
    for name in ("index.html", "styles.css", "app.js"):
        assert (STATIC_DIR / name).is_file(), name


def test_serve_command_listed() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout
