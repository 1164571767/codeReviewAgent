"""The ``Node`` protocol.

Every unit of work in a workflow — including every agent — is a node: it has a
name and transforms the shared :class:`WorkflowState`. Nodes never reference
each other; the :class:`~code_agent.workflow.Workflow` owns the topology. That
seam is what lets project 2 swap the linear runner for a graph of agents.
"""

from __future__ import annotations

from typing import ClassVar, Protocol

from code_agent.state import WorkflowState


class Node(Protocol):
    name: ClassVar[str]

    async def run(self, state: WorkflowState) -> WorkflowState: ...
