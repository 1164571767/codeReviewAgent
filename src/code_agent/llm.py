"""LLM client: OpenAI async SDK + timeout, retries and error classification.

All network calls funnel through here so the retry/timeout policy lives in
exactly one place (DESIGN.md section 9).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel, Field
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from code_agent.config import AgentConfig
from code_agent.errors import ConfigError, LLMBusyError, LLMError
from code_agent.logging_setup import get_logger
from code_agent.message import AgentMessage, ToolCall

log = get_logger("llm")


class LLMResult(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""


@runtime_checkable
class LLMClient(Protocol):
    """Anything that can answer a chat request. ``FakeLLM`` implements this."""

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> LLMResult: ...


def is_transient(exc: BaseException) -> bool:
    """Whether a failed call is worth retrying."""
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return False


class OpenAILLMClient:
    """Concrete :class:`LLMClient` backed by the OpenAI async SDK."""

    def __init__(self, config: AgentConfig, client: Any | None = None) -> None:
        self._config = config
        self._client = client or AsyncOpenAI(
            api_key=config.require_api_key(),
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=0,  # retries are owned by our tenacity layer
        )

    async def chat(
        self,
        messages: Sequence[AgentMessage],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> LLMResult:
        try:
            return await self._call_with_retry(messages, tools, temperature)
        except AuthenticationError as exc:
            raise ConfigError(f"LLM authentication failed: {exc}") from exc
        except (APITimeoutError, APIConnectionError, RateLimitError) as exc:
            raise LLMBusyError(f"LLM unavailable after retries: {exc}") from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMBusyError(f"LLM server error after retries: {exc}") from exc
            raise LLMError(f"LLM request rejected ({exc.status_code}): {exc}") from exc
        except APIError as exc:
            raise LLMError(str(exc)) from exc

    async def _call_with_retry(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float | None,
    ) -> LLMResult:
        retryer = AsyncRetrying(
            stop=stop_after_attempt(self._config.max_retries + 1),
            wait=wait_exponential_jitter(initial=0.5, max=20),
            retry=retry_if_exception(is_transient),
            reraise=True,
        )
        async for attempt in retryer:
            with attempt:
                number = attempt.retry_state.attempt_number
                if number > 1:
                    log.warning("retrying llm call", extra={"kv": {"attempt": number}})
                return await self._call(messages, tools, temperature)
        raise LLMError("retry loop exited without a result")

    async def _call(
        self,
        messages: Sequence[AgentMessage],
        tools: Sequence[dict[str, Any]] | None,
        temperature: float | None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": self._config.temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        response = await self._client.chat.completions.create(**payload)
        return self._parse(response)

    @staticmethod
    def _parse(response: Any) -> LLMResult:
        message = response.choices[0].message
        calls: list[ToolCall] = []
        for raw in getattr(message, "tool_calls", None) or []:
            try:
                arguments = json.loads(raw.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(ToolCall(id=raw.id, name=raw.function.name, arguments=arguments))
        usage = getattr(response, "usage", None)
        return LLMResult(
            content=message.content,
            tool_calls=calls,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=getattr(response, "model", "") or "",
        )
