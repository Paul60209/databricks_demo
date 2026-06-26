import json
import re

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from .state import AgentState

_MAX_ITERATIONS = 3

_SYSTEM_PROMPT = """You are a quality evaluator for a business intelligence AI assistant.
Assess whether the Think Agent's answer fully and accurately answers the user's original question
using the data retrieved from Databricks.

Evaluation criteria:
  1. RELEVANCE: Does the answer directly address what was asked?
  2. DATA GROUNDING: Are the numbers and claims supported by the tool results shown?
  3. COMPLETENESS: Are all significant aspects of the question addressed?
  4. CLARITY: Is the answer understandable to a business user?

Respond ONLY with a JSON object — no prose before or after.
Format: {"verdict": "PASS" or "FAIL", "feedback": "specific actionable critique if FAIL, empty string if PASS"}"""

_MAX_TOOL_RESULT_CHARS = 8000


async def judge_node(state: AgentState) -> dict:
    llm = ChatAnthropic(model="claude-haiku-4-5-20251001", temperature=0)

    # Truncate tool results if very large to keep the prompt manageable
    tool_results_str = json.dumps(state["tool_results"], ensure_ascii=False, indent=2)
    if len(tool_results_str) > _MAX_TOOL_RESULT_CHARS:
        tool_results_str = tool_results_str[:_MAX_TOOL_RESULT_CHARS] + "\n... (truncated)"

    prompt = HumanMessage(content=(
        f"User question: {state['user_question']}\n\n"
        f"Think Agent's answer:\n{state['think_answer']}\n\n"
        f"Raw tool results for verification:\n{tool_results_str}\n\n"
        f"Evaluate and respond with JSON only."
    ))

    response = await llm.ainvoke([SystemMessage(content=_SYSTEM_PROMPT), prompt])

    # Parse JSON; extract from prose if needed; fallback to PASS on failure
    verdict = "PASS"
    feedback = ""
    try:
        raw = response.content
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            verdict = parsed.get("verdict", "PASS")
            feedback = parsed.get("feedback", "")
    except (json.JSONDecodeError, AttributeError):
        pass  # fallback: PASS

    force_complete = state["iteration_count"] >= _MAX_ITERATIONS

    if verdict == "PASS" or force_complete:
        return {
            "is_complete": True,
            "final_answer": state["think_answer"],
            "judge_feedback": "",
        }
    else:
        return {
            "is_complete": False,
            "judge_feedback": feedback,
            "final_answer": "",
        }
