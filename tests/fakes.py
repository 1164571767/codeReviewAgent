"""Shared test doubles."""

from __future__ import annotations

from typing import Any

from code_agent.llm import LLMResult
from code_agent.message import AgentMessage


class FakeLLM:
    """Returns pre-scripted results in order; records each request."""

    def __init__(self, script: list[LLMResult]) -> None:
        self._script = list(script)
        self.requests: list[list[AgentMessage]] = []

    async def chat(
        self,
        messages: Any,
        *,
        tools: Any = None,
        temperature: float | None = None,
    ) -> LLMResult:
        self.requests.append(list(messages))
        if not self._script:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._script.pop(0)
