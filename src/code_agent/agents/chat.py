"""Chat agent: a conversational agent with no terminal tool.

Kept separate from ``ReviewerAgent`` because the loop shape differs: chat ends
a turn on a plain answer (``finish_tool is None``) instead of on a report tool.
"""

from __future__ import annotations

from pathlib import Path

from code_agent.base_agent import BaseAgent
from code_agent.config import AgentConfig
from code_agent.llm import LLMClient
from code_agent.memory import JSONMemory
from code_agent.prompts import build_chat_prompt
from code_agent.report import UsageStats
from code_agent.state import WorkflowState
from code_agent.tools.registry import ToolRegistry

REPLY_KEY = "reply"


class ChatAgent(BaseAgent):
    name = "ChatAgent"
    finish_tool = None

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        config: AgentConfig,
        root: Path,
        memory: JSONMemory | None = None,
    ) -> None:
        self.system_prompt = build_chat_prompt(root)
        super().__init__(llm, tools, config, memory)

    async def run(self, state: WorkflowState) -> WorkflowState:
        # Budget guard is per-turn here: usage accumulates across a long
        # session and would otherwise trip on the first message.
        state.usage = UsageStats()
        return await super().run(state)
