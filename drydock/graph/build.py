"""Wire nodes and edges into a compiled LangGraph (docs/design/03-lld.md section 7.1).

START -> load_spec -> plan -> generate -> evaluate -> [route]
  route: passed -> await_approval; failed and budget left -> generate; else escalate -> END
await_approval -(approve)-> publish -> END
await_approval -(reject)-> record_rejection -> END
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from drydock.graph import state as st
from drydock.graph.nodes import Deps, Nodes
from drydock.models import GraphState


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:  # type: ignore[type-arg]
    """Compile the DRYDOCK loop with ``deps`` bound into every node."""
    nodes = Nodes(deps)
    graph: StateGraph = StateGraph(GraphState)  # type: ignore[type-arg]
    graph.add_node(st.LOAD_SPEC, nodes.load_spec)
    graph.add_node(st.PLAN, nodes.plan)
    graph.add_node(st.GENERATE, nodes.generate)
    graph.add_node(st.EVALUATE, nodes.evaluate)
    graph.add_node(st.AWAIT_APPROVAL, nodes.await_approval)
    graph.add_node(st.PUBLISH, nodes.publish)
    graph.add_node(st.RECORD_REJECTION, nodes.record_rejection)
    graph.add_node(st.ESCALATE, nodes.escalate)

    graph.add_edge(START, st.LOAD_SPEC)
    graph.add_edge(st.LOAD_SPEC, st.PLAN)
    graph.add_edge(st.PLAN, st.GENERATE)
    graph.add_edge(st.GENERATE, st.EVALUATE)
    graph.add_conditional_edges(
        st.EVALUATE,
        st.route_after_evaluate,
        {"approve": st.AWAIT_APPROVAL, "repair": st.GENERATE, "escalate": st.ESCALATE},
    )
    graph.add_conditional_edges(
        st.AWAIT_APPROVAL,
        st.route_after_decision,
        {"approve": st.PUBLISH, "reject": st.RECORD_REJECTION},
    )
    graph.add_edge(st.PUBLISH, END)
    graph.add_edge(st.RECORD_REJECTION, END)
    graph.add_edge(st.ESCALATE, END)
    return graph.compile(checkpointer=checkpointer)


__all__ = ["build_graph"]
