"""End-to-end tests for the Collector -> Reviewer -> Reporter pipeline."""

from __future__ import annotations

from pathlib import Path

from code_agent.agents.collector import CollectorNode
from code_agent.agents.reporter import ReporterNode
from code_agent.agents.reviewer import ReviewerAgent
from code_agent.config import AgentConfig
from code_agent.llm import LLMResult
from code_agent.message import ToolCall
from code_agent.report import Finding, ReviewReport, Severity, render_markdown
from code_agent.state import ReviewTask, WorkflowState
from code_agent.tools.builtin import build_default_registry
from code_agent.workflow import Workflow
from fakes import FakeLLM


def _pipeline(llm: FakeLLM, **config: object) -> Workflow:
    settings = AgentConfig(api_key="sk-test", **config)
    return Workflow(
        [
            CollectorNode(),
            ReviewerAgent(llm, build_default_registry(), settings),
            ReporterNode(),
        ]
    )


def _state(target: Path, **kwargs: object) -> WorkflowState:
    return WorkflowState(run_id="r1", task=ReviewTask(target=target, **kwargs))


def _submit(arguments: dict[str, object]) -> LLMResult:
    call = ToolCall(id="c9", name="submit_review", arguments=dict(arguments))
    return LLMResult(tool_calls=[call])


def _finding(file: str) -> dict[str, object]:
    return {
        "id": "F-001",
        "severity": "high",
        "category": "security",
        "file": file,
        "line": 5,
        "title": "SQL 注入",
        "detail": "使用字符串拼接构造 SQL。",
    }


async def test_pipeline_produces_report_and_markdown(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    target.write_text("query = 'SELECT %s' % name\n", encoding="utf-8")

    llm = FakeLLM(
        [
            LLMResult(
                tool_calls=[ToolCall(id="c1", name="read_file", arguments={"path": str(target)})]
            ),
            _submit(
                {
                    "summary": "存在一处安全风险。",
                    "score": 60,
                    "files_reviewed": [str(target)],
                    "findings": [_finding(str(target))],
                }
            ),
        ]
    )

    state = await _pipeline(llm).run(_state(target))

    assert state.status == "done"
    assert state.report is not None
    assert state.report.score == 60
    assert state.report.model == "gpt-4o-mini"
    assert len(state.report.findings) == 1
    assert state.usage.llm_calls == 2
    markdown = state.artifacts["markdown"]
    assert "# 代码审查报告" in markdown
    assert "SQL 注入" in markdown


async def test_collector_expands_directory(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "note.txt").write_text("ignore\n", encoding="utf-8")

    llm = FakeLLM([_submit({"summary": "clean", "score": 100})])
    state = await _pipeline(llm).run(_state(tmp_path))

    assert len(state.files) == 2
    assert all(name.endswith(".py") for name in state.files)
    assert state.report is not None
    assert sorted(state.report.files_reviewed) == sorted(state.files)


async def test_collector_missing_path_short_circuits(tmp_path: Path) -> None:
    llm = FakeLLM([])
    state = await _pipeline(llm).run(_state(tmp_path / "nope.py"))

    assert state.status == "failed"
    assert "path not found" in (state.error or "")
    assert llm.requests == []


async def test_degrade_produces_partial_report(tmp_path: Path) -> None:
    target = tmp_path / "bad.py"
    target.write_text("x = 1\n", encoding="utf-8")

    bad = {"summary": "s", "score": 999, "findings": [_finding(str(target))]}
    llm = FakeLLM([_submit(bad), _submit(bad), _submit(bad)])

    state = await _pipeline(llm, max_repairs=1).run(_state(target))

    assert state.report is not None
    assert "部分结果" in state.report.summary
    assert len(state.report.findings) == 1


async def test_reviewer_registers_submit_tool() -> None:
    tools = build_default_registry()
    ReviewerAgent(FakeLLM([]), tools, AgentConfig(api_key="sk-test"))
    assert "submit_review" in tools
    assert len(tools) == 5


def test_render_markdown_no_findings() -> None:
    markdown = render_markdown(ReviewReport(summary="干净", score=100))
    assert "未发现明显问题" in markdown


def test_render_markdown_orders_by_severity() -> None:
    low = Finding(
        id="F-1", severity=Severity.low, category="style", file="a.py", title="low", detail="d"
    )
    critical = Finding(
        id="F-2",
        severity=Severity.critical,
        category="bug",
        file="a.py",
        line=1,
        title="critical",
        detail="d",
        evidence="boom()",
    )
    markdown = render_markdown(ReviewReport(summary="s", score=10, findings=[low, critical]))
    assert markdown.index("critical") < markdown.index("| low |")
    assert "```python" in markdown
