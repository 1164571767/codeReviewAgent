"""Tests for AgentConfig."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from code_agent.config import DEFAULT_MODEL, AgentConfig
from code_agent.errors import ConfigError


def test_defaults_without_env() -> None:
    config = AgentConfig.from_env({})
    assert config.model == DEFAULT_MODEL
    assert config.api_key is None
    assert config.base_url is None


def test_env_overrides() -> None:
    config = AgentConfig.from_env(
        {
            "CODE_AGENT_MODEL": "deepseek-chat",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "https://api.example.com/v1",
        }
    )
    assert config.model == "deepseek-chat"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://api.example.com/v1"


def test_blank_env_values_fall_back() -> None:
    config = AgentConfig.from_env({"CODE_AGENT_MODEL": "", "OPENAI_BASE_URL": ""})
    assert config.model == DEFAULT_MODEL
    assert config.base_url is None


def test_require_api_key_raises_when_missing() -> None:
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        AgentConfig().require_api_key()


def test_require_api_key_returns_value() -> None:
    assert AgentConfig(api_key="sk-abc").require_api_key() == "sk-abc"


def test_invalid_bounds_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(max_iterations=0)
