"""
Sony AI Chatbot — LangGraph Multi-Agent CLI

Usage:
    python run_agent.py "Taiwan 地區 2025 年 Q1 的 AOV 趨勢"
    python run_agent.py "Which customer had the highest spend in 2025-01?" --verbose
"""

import asyncio
import argparse
from pathlib import Path

# load_dotenv MUST run before any imports that read env vars
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

from langchain_core.messages import HumanMessage  # noqa: E402

from agent.mcp_client import make_mcp_client  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.state import AgentState  # noqa: E402


async def run(question: str, verbose: bool = False) -> str:
    client = make_mcp_client()

    tools = await client.get_tools()

    if verbose:
        print(f"[INFO] Loaded {len(tools)} MCP tools: {[t.name for t in tools]}")

    graph = build_graph(tools)

    initial_state: AgentState = {
        "messages": [HumanMessage(content=question)],
        "user_question": question,
        "tool_results": [],
        "think_answer": "",
        "judge_feedback": "",
        "iteration_count": 0,
        "final_answer": "",
        "is_complete": False,
    }

    result = await graph.ainvoke(initial_state)

    if verbose:
        print(f"[INFO] Completed in {result['iteration_count']} iteration(s)")
        print(f"[INFO] Tool calls made: {len(result['tool_results'])}")

    return result["final_answer"]


def main():
    parser = argparse.ArgumentParser(
        description="Sony AI Chatbot — LangGraph Multi-Agent CLI"
    )
    parser.add_argument("question", help="Natural language business question")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print iteration count and tool info",
    )
    args = parser.parse_args()

    answer = asyncio.run(run(args.question, verbose=args.verbose))
    print("\n" + "=" * 60)
    print("FINAL ANSWER")
    print("=" * 60)
    print(answer)


if __name__ == "__main__":
    main()
