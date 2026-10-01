"""Exception hierarchy for the code review agent.

See DESIGN.md section 9. Every error raised by the agent descends from
``AgentError`` so the CLI can map it to an exit code in one place.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all agent errors."""


class ConfigError(AgentError):
    """Configuration, credential or usage problem. Never retried."""


class LLMError(AgentError):
    """Generic LLM call failure."""


class LLMBusyError(LLMError):
    """Transient LLM failure (timeout / 429 / 5xx) that survived retries."""


class ToolError(AgentError):
    """Tool execution failure.

    Tools normally swallow their own errors into ``{"ok": false, ...}``
    results; this is reserved for failures of the tool machinery itself.
    """


class ReviewError(AgentError):
    """The agent could not produce a terminal review report."""
