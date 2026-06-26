from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from .state import AgentState

_MAX_TOOL_ROUNDS = 5

_SYSTEM_PROMPT = """You are a data analyst for Sony's business intelligence platform.
You have access to Databricks tools that query a customer transaction database.

Tools available:
  - get_customer_transaction_summary: per-customer monthly stats (count, amount, AOV)
  - get_regional_monthly_aov: AOV aggregated by country and month
  - query_data_with_natural_language: text-to-SQL for ad-hoc questions that don't fit the above tools

Strategy:
1. Analyze what data the question requires.
2. Choose the most appropriate tool(s). Prefer the typed query tools over query_data_with_natural_language when the question fits them.
3. Call the tool(s), then synthesize the raw JSON results into a clear, business-focused answer.
4. Always include specific numbers from the tool results. Do not make up or estimate data.
5. If a previous attempt was flagged as insufficient, directly address the specific feedback provided."""


def create_think_node(tools: list):
    """Factory that closes over the live MCP tool instances."""
    llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
    llm_with_tools = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}

    async def think_node(state: AgentState) -> dict:
        # Build the working message list for this invocation
        work_messages = [SystemMessage(content=_SYSTEM_PROMPT)] + list(state["messages"])

        # On retry: surface judge feedback as a new human turn
        if state.get("judge_feedback"):
            work_messages.append(
                HumanMessage(content=(
                    f"Your previous answer was flagged as insufficient.\n"
                    f"Feedback: {state['judge_feedback']}\n"
                    f"Please reconsider and provide a more complete answer."
                ))
            )

        new_messages: list = []
        new_tool_results = list(state.get("tool_results", []))
        final_text = ""

        for _ in range(_MAX_TOOL_ROUNDS):
            response = await llm_with_tools.ainvoke(work_messages)
            work_messages.append(response)
            new_messages.append(response)

            if not response.tool_calls:
                final_text = response.content
                break

            for tool_call in response.tool_calls:
                tool = tool_map[tool_call["name"]]
                result = await tool.ainvoke(tool_call["args"])
                tool_msg = ToolMessage(
                    content=str(result),
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                )
                work_messages.append(tool_msg)
                new_messages.append(tool_msg)
                new_tool_results.append({
                    "tool": tool_call["name"],
                    "args": tool_call["args"],
                    "result": str(result),
                })

        return {
            "messages": new_messages,
            "think_answer": final_text,
            "tool_results": new_tool_results,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    return think_node
