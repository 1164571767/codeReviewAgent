"""Runtime configuration loaded from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel, Field

from code_agent.errors import ConfigError

ENV_API_KEY = "OPENAI_API_KEY"
ENV_BASE_URL = "OPENAI_BASE_URL"
ENV_MODEL = "CODE_AGENT_MODEL"

DEFAULT_MODEL = "gpt-4o-mini"


class AgentConfig(BaseModel):
    """Tunable knobs for a single agent run.

    ``base_url`` stays optional so the same client can talk to the official
    OpenAI endpoint or any OpenAI-compatible endpoint (DeepSeek, local, ...).
    """

    model: str = DEFAULT_MODEL
    api_key: str | None = None
    base_url: str | None = None

    timeout: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=4, ge=0)
    max_iterations: int = Field(default=12, ge=1)
    token_budget: int = Field(default=60_000, gt=0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AgentConfig:
        source = os.environ if env is None else env
        return cls(
            model=source.get(ENV_MODEL) or DEFAULT_MODEL,
            api_key=source.get(ENV_API_KEY) or None,
            base_url=source.get(ENV_BASE_URL) or None,
        )

    def require_api_key(self) -> str:
        if not self.api_key:
            raise ConfigError(f"{ENV_API_KEY} is not set")
        return self.api_key
