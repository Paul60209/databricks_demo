from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class AgentState(TypedDict):
    messages:        Annotated[list[BaseMessage], add_messages]
    user_question:   str
    tool_results:    list[dict]   # accumulated {tool, args, result} dicts
    think_answer:    str          # most recent prose answer from Think Agent
    judge_feedback:  str          # Judge's critique; empty string on PASS
    iteration_count: int
    final_answer:    str          # set by Judge on approval
    is_complete:     bool
