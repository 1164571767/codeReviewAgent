"""Tests for the tool registry."""

from __future__ import annotations

import pytest

from code_agent.errors import ToolError
from code_agent.tools.registry import Tool, ToolRegistry


def _tool(name: str = "echo", func: object = None) -> Tool:
    return Tool(
        name=name,
        description="echo back",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        func=func or (lambda text: {"ok": True, "text": text}),
    )


def test_register_and_get() -> None:
    registry = ToolRegistry([_tool()])
    assert "echo" in registry
    assert registry.names() == ["echo"]
    assert len(registry) == 1
    assert registry.get("echo").name == "echo"


def test_duplicate_register_raises() -> None:
    registry = ToolRegistry([_tool()])
    with pytest.raises(ToolError, match="duplicate"):
        registry.register(_tool())


def test_get_unknown_raises() -> None:
    with pytest.raises(ToolError, match="unknown tool"):
        ToolRegistry().get("nope")


def test_schema_shape() -> None:
    schema = ToolRegistry([_tool()]).schemas()[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "echo"
    assert schema["function"]["parameters"]["required"] == ["text"]


def test_call_success() -> None:
    result = ToolRegistry([_tool()]).call("echo", {"text": "hi"})
    assert result == {"ok": True, "text": "hi"}


def test_call_unknown_tool_returns_error_not_raises() -> None:
    result = ToolRegistry().call("missing", {})
    assert result["ok"] is False
    assert "unknown tool" in result["error"]


def test_call_bad_arguments_returns_error() -> None:
    result = ToolRegistry([_tool()]).call("echo", {})
    assert result["ok"] is False
    assert "bad arguments" in result["error"]


def test_call_wraps_tool_exception() -> None:
    def boom(text: str) -> dict[str, object]:
        raise RuntimeError("kaboom")

    result = ToolRegistry([_tool(func=boom)]).call("echo", {"text": "x"})
    assert result["ok"] is False
    assert "kaboom" in result["error"]


def test_call_rejects_non_dict_result() -> None:
    result = ToolRegistry([_tool(func=lambda text: "nope")]).call("echo", {"text": "x"})
    assert result["ok"] is False
    assert "expected dict" in result["error"]
