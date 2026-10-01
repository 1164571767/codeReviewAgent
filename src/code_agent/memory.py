"""JSON-backed memory and context trimming.

Two jobs:

* persist the serialisable slice of a :class:`WorkflowState` to
  ``.code_agent/runs/<run_id>.json`` so a run can be revisited or resumed;
* trim the conversation to a token budget before each LLM call while keeping
  ``assistant(tool_calls)`` and its ``tool`` results paired.

Token counts use a character heuristic (no tokenizer dependency), which is
plenty for budgeting.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from code_agent.message import AgentMessage
from code_agent.state import WorkflowState

DEFAULT_RUN_DIR = Path(".code_agent") / "runs"
CHARS_PER_TOKEN = 4


def estimate_tokens(
    messages: Sequence[AgentMessage],
    chars_per_token: int = CHARS_PER_TOKEN,
) -> int:
    """Rough token estimate for a list of messages."""
    chars = 0
    for message in messages:
        chars += len(message.content or "")
        for call in message.tool_calls:
            chars += len(call.name) + len(json.dumps(call.arguments))
        chars += 8  # per-message overhead
    return max(1, chars // chars_per_token)


class JSONMemory:
    def __init__(
        self,
        root: Path = DEFAULT_RUN_DIR,
        token_budget: int = 60_000,
        chars_per_token: int = CHARS_PER_TOKEN,
    ) -> None:
        self.root = Path(root)
        self.token_budget = token_budget
        self.chars_per_token = chars_per_token

    def path_for(self, run_id: str) -> Path:
        return self.root / f"{run_id}.json"

    def save(self, state: WorkflowState) -> Path:
        path = self.path_for(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, run_id: str) -> WorkflowState:
        return WorkflowState.model_validate_json(self.path_for(run_id).read_text(encoding="utf-8"))

    def estimate(self, messages: Sequence[AgentMessage]) -> int:
        return estimate_tokens(messages, self.chars_per_token)

    def build_context(
        self,
        state: WorkflowState,
        budget: int | None = None,
    ) -> list[AgentMessage]:
        """Return the messages to send, newest-biased and within budget."""
        limit = self.token_budget if budget is None else budget
        messages = list(state.messages)
        if not messages:
            return []

        system: list[AgentMessage] = []
        body = messages
        if messages[0].role == "system":
            system = [messages[0]]
            body = messages[1:]

        used = self.estimate(system)
        kept: list[AgentMessage] = []
        for message in reversed(body):
            cost = self.estimate([message])
            if kept and used + cost > limit:
                break
            kept.append(message)
            used += cost
        kept.reverse()

        # A tool result must never appear without the assistant call that made it.
        while kept and kept[0].role == "tool":
            kept.pop(0)

        return system + kept
