"""Tool registry.

Tools are plain callables returning JSON-serialisable dicts. They never raise
into the agent loop: :meth:`ToolRegistry.call` converts any failure into
``{"ok": false, "error": ...}`` so the model can recover (DESIGN.md section 8).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from code_agent.errors import ToolError

ToolResult = dict[str, Any]
ToolFunc = Callable[..., ToolResult]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: ToolFunc

    def schema(self) -> dict[str, Any]:
        """OpenAI ``tools`` entry for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ToolError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def names(self) -> list[str]:
        return list(self._tools)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolError(f"unknown tool: {name}") from None

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Invoke a tool, never raising into the agent loop."""
        if name not in self._tools:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            result = self._tools[name].func(**arguments)
        except TypeError as exc:  # bad/missing arguments from the model
            return {"ok": False, "error": f"bad arguments: {exc}"}
        except Exception as exc:  # noqa: BLE001 - reported to the model, not raised
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not isinstance(result, dict):
            return {"ok": False, "error": f"tool returned {type(result).__name__}, expected dict"}
        return result
