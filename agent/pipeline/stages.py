"""Run a pipeline's stages as a Strands Agents Graph (ASPPH Technical Document: "Strands agents on AgentCore").

Each stage (map to CEPH → find sources → write edits → Supervisor) is a node of a Strands Graph, joined by
fixed edges, so the order never changes: professors get the same checked sequence every time. Inside a node,
the stage makes its Claude call through llm.call exactly as before (structured output, effort, stop-reason
checks), so moving to Strands changes the orchestration, not the answers.

    PHACT_ORCHESTRATOR=strands   (default) Strands Graph
    PHACT_ORCHESTRATOR=plain     the same stages in a plain loop (fallback, and for A/B comparison)

A stage is fn(state) that reads and writes the shared `state` dict; its time lands in state["timings"].
"""

import asyncio
import os
import time
from typing import Callable

Stage = tuple[str, Callable[[dict], None]]


def _timed(name: str, fn: Callable[[dict], None], state: dict) -> None:
    t = time.monotonic()
    fn(state)
    state.setdefault("timings", {})[name] = int((time.monotonic() - t) * 1000)


def _plain(stages: list[Stage], state: dict) -> None:
    for name, fn in stages:
        _timed(name, fn, state)


def _strands(graph_id: str, stages: list[Stage], state: dict) -> None:
    from strands.multiagent import GraphBuilder, MultiAgentBase, MultiAgentResult
    from strands.multiagent.base import Status

    class StageNode(MultiAgentBase):
        """A deterministic Strands node: runs one PHACT stage on the shared state."""

        def __init__(self, name: str, fn: Callable[[dict], None]):
            super().__init__()
            self.name, self.id, self.fn = name, name, fn

        async def invoke_async(self, task, invocation_state=None, **kwargs) -> MultiAgentResult:
            st = (invocation_state or {})["phact"]
            t = time.monotonic()
            try:
                await asyncio.to_thread(_timed, self.name, self.fn, st)
            except Exception as e:  # noqa: BLE001 — kept for the caller; the graph stops here
                st["_error"] = e
                raise
            return MultiAgentResult(status=Status.COMPLETED, execution_time=int((time.monotonic() - t) * 1000))

    b = GraphBuilder()
    for name, fn in stages:
        b.add_node(StageNode(name, fn), name)
    for (a, _), (z, _) in zip(stages, stages[1:]):
        b.add_edge(a, z)
    b.set_entry_point(stages[0][0])
    b.set_graph_id(graph_id)
    b.set_execution_timeout(900)
    b.set_node_timeout(600)
    graph = b.build()
    result = graph(f"PHACT {graph_id}", invocation_state={"phact": state})
    if "_error" in state:
        raise state.pop("_error")
    if result.status != Status.COMPLETED:
        raise RuntimeError(f"Strands graph {graph_id} ended {result.status.value}")
    state["orchestrator"] = {"name": "strands-graph", "nodes": [n for n, _ in stages],
                             "completed": [n for n, r in result.results.items() if r.status == Status.COMPLETED]}


def run_stages(graph_id: str, stages: list[Stage], state: dict) -> dict:
    if os.getenv("PHACT_ORCHESTRATOR", "strands") == "strands":
        try:
            import strands  # noqa: F401
        except ImportError:
            _plain(stages, state)
            state["orchestrator"] = {"name": "plain", "note": "strands not installed"}
            return state
        _strands(graph_id, stages, state)
    else:
        _plain(stages, state)
        state["orchestrator"] = {"name": "plain"}
    return state
