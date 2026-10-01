"""Linear workflow runner.

The only place that knows the topology. Project 1 runs nodes in order; project
2 replaces this loop with a graph scheduler (conditional edges, fan-out,
parallel branches) without touching a single node.
"""

from __future__ import annotations

from collections.abc import Sequence

from code_agent.logging_setup import get_logger
from code_agent.node import Node
from code_agent.state import TraceEvent, WorkflowState

log = get_logger("workflow")


class Workflow:
    def __init__(self, nodes: Sequence[Node]) -> None:
        self._nodes = list(nodes)

    @property
    def nodes(self) -> list[Node]:
        return list(self._nodes)

    async def run(self, state: WorkflowState) -> WorkflowState:
        for node in self._nodes:
            state.node = node.name
            state.trace.append(TraceEvent(node=node.name, event="node_start"))
            log.info("node start", extra={"kv": {"node": node.name}})

            state = await node.run(state)

            failed = state.status == "failed"
            state.trace.append(TraceEvent(node=node.name, event="node_end", ok=not failed))
            log.info(
                "node end",
                extra={"kv": {"node": node.name, "status": state.status, "ok": not failed}},
            )
            if failed:
                break
        return state
