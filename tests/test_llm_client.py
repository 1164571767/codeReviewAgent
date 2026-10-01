"""Tests for the LLM client (no network; stub transport + monkeypatched backoff)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx2 as httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from tenacity import wait_none

from code_agent import llm as llm_module
from code_agent.config import AgentConfig
from code_agent.errors import ConfigError, LLMBusyError, LLMError
from code_agent.llm import OpenAILLMClient, is_transient
from code_agent.message import AgentMessage

_URL = "https://api.example.com/v1/chat/completions"


def _request() -> httpx.Request:
    return httpx.Request("POST", _URL)


def _status_error(cls: type[Exception], code: int, message: str = "err") -> Exception:
    response = httpx.Response(code, request=_request())
    return cls(message, response=response, body=None)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_module, "wait_exponential_jitter", lambda **_: wait_none())


def _response(
    content: str | None = None,
    tool_calls: list[Any] | None = None,
    *,
    prompt: int = 10,
    completion: int = 5,
    model: str = "gpt-4o-mini",
) -> Any:
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model=model)


def _tool_call(call_id: str, name: str, arguments: str) -> Any:
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class _StubCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _client(outcomes: list[Any]) -> tuple[OpenAILLMClient, _StubCompletions]:
    completions = _StubCompletions(outcomes)
    stub = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return OpenAILLMClient(AgentConfig(api_key="sk-test", max_retries=2), client=stub), completions


_MESSAGES = [AgentMessage(id="m1", role="user", content="review this")]


async def test_parses_content_and_usage() -> None:
    client, _ = _client([_response("hello", prompt=7, completion=3)])
    result = await client.chat(_MESSAGES)
    assert result.content == "hello"
    assert result.prompt_tokens == 7
    assert result.completion_tokens == 3


async def test_parses_tool_calls() -> None:
    call = _tool_call("c1", "read_file", '{"path": "a.py"}')
    client, _ = _client([_response(tool_calls=[call])])
    result = await client.chat(_MESSAGES, tools=[{"type": "function"}])
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "a.py"}


async def test_malformed_tool_arguments_become_empty_dict() -> None:
    call = _tool_call("c1", "read_file", "{not json")
    client, _ = _client([_response(tool_calls=[call])])
    result = await client.chat(_MESSAGES)
    assert result.tool_calls[0].arguments == {}


async def test_retries_transient_then_succeeds() -> None:
    client, completions = _client([_status_error(RateLimitError, 429), _response("ok")])
    result = await client.chat(_MESSAGES)
    assert result.content == "ok"
    assert completions.calls == 2


async def test_auth_error_is_not_retried() -> None:
    client, completions = _client([_status_error(AuthenticationError, 401, "bad key")])
    with pytest.raises(ConfigError):
        await client.chat(_MESSAGES)
    assert completions.calls == 1


async def test_transient_exhaustion_raises_busy() -> None:
    outcomes = [_status_error(RateLimitError, 429) for _ in range(3)]
    client, completions = _client(outcomes)
    with pytest.raises(LLMBusyError):
        await client.chat(_MESSAGES)
    assert completions.calls == 3  # max_retries(2) + 1


async def test_client_error_is_not_retried() -> None:
    client, completions = _client([_status_error(BadRequestError, 400)])
    with pytest.raises(LLMError):
        await client.chat(_MESSAGES)
    assert completions.calls == 1


async def test_timeout_retried_then_busy() -> None:
    outcomes = [
        APITimeoutError(request=_request()),
        APIConnectionError(request=_request()),
        APITimeoutError(request=_request()),
    ]
    client, completions = _client(outcomes)
    with pytest.raises(LLMBusyError):
        await client.chat(_MESSAGES)
    assert completions.calls == 3


def test_missing_api_key_raises_config_error() -> None:
    with pytest.raises(ConfigError):
        OpenAILLMClient(AgentConfig())


def test_is_transient_classification() -> None:
    assert is_transient(_status_error(RateLimitError, 429))
    assert is_transient(_status_error(InternalServerError, 503))
    assert is_transient(APITimeoutError(request=_request()))
    assert not is_transient(_status_error(BadRequestError, 400))
    assert not is_transient(ValueError("nope"))
