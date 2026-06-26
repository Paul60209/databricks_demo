from langgraph.graph import StateGraph, END

from .state import AgentState
from .think_agent import create_think_node
from .judge_agent import judge_node


def route_after_judge(state: AgentState) -> str:
    if state["is_complete"] or state["iteration_count"] >= 3:
        return END
    return "think"


def build_graph(tools: list):
    """Build and compile the Think → Judge StateGraph."""
    graph = StateGraph(AgentState)

    graph.add_node("think", create_think_node(tools))
    graph.add_node("judge", judge_node)

    graph.set_entry_point("think")
    graph.add_edge("think", "judge")
    graph.add_conditional_edges(
        "judge",
        route_after_judge,
        {"think": "think", END: END},
    )

    return graph.compile()
