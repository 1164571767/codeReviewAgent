"""Tests for the linear Workflow runner."""

from __future__ import annotations

from pathlib import Path

from code_agent.state import ReviewTask, WorkflowState
from code_agent.workflow import Workflow


class RecordingNode:
    def __init__(self, name: str, *, fail: bool = False, tag: str | None = None) -> None:
        self.name = name
        self._fail = fail
        self._tag = tag
        self.seen_statuses: list[str] = []

    async def run(self, state: WorkflowState) -> WorkflowState:
        self.seen_statuses.append(state.status)
        if self._tag:
            state.files.append(self._tag)
        if self._fail:
            state.status = "failed"
        else:
            state.status = "done"
        return state


def _state() -> WorkflowState:
    return WorkflowState(run_id="r1", task=ReviewTask(target=Path("x.py")))


async def test_nodes_run_in_order() -> None:
    nodes = [RecordingNode("a", tag="a"), RecordingNode("b", tag="b"), RecordingNode("c", tag="c")]
    state = await Workflow(nodes).run(_state())
    assert state.files == ["a", "b", "c"]


async def test_state_is_shared_across_nodes() -> None:
    first = RecordingNode("a", tag="x")
    second = RecordingNode("b", tag="y")
    state = await Workflow([first, second]).run(_state())
    assert state.files == ["x", "y"]
    assert second.seen_statuses == ["done"]


async def test_failure_short_circuits() -> None:
    nodes = [
        RecordingNode("a", tag="a"),
        RecordingNode("b", fail=True),
        RecordingNode("c", tag="c"),
    ]
    state = await Workflow(nodes).run(_state())
    assert state.status == "failed"
    assert state.files == ["a"]  # "c" never ran


async def test_trace_records_node_boundaries() -> None:
    state = await Workflow([RecordingNode("a"), RecordingNode("b", fail=True)]).run(_state())
    events = [(e.node, e.event, e.ok) for e in state.trace]
    assert events == [
        ("a", "node_start", True),
        ("a", "node_end", True),
        ("b", "node_start", True),
        ("b", "node_end", False),
    ]


async def test_current_node_is_set_during_run() -> None:
    seen: list[str | None] = []

    class Spy:
        name = "spy"

        async def run(self, state: WorkflowState) -> WorkflowState:
            seen.append(state.node)
            return state

    await Workflow([Spy()]).run(_state())
    assert seen == ["spy"]


def test_nodes_property_is_a_copy() -> None:
    node = RecordingNode("a")
    workflow = Workflow([node])
    workflow.nodes.append(RecordingNode("b"))
    assert [n.name for n in workflow.nodes] == ["a"]
