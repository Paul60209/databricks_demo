"""
Sony BI Chatbot — Chainlit Frontend

Run:
    chainlit run front_end/chainlit_app.py --port 8000
"""

import sys
from pathlib import Path

# Allow importing agent/ from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import chainlit as cl
from langchain_core.messages import HumanMessage

from agent.mcp_client import make_mcp_client
from agent.graph import build_graph
from agent.state import AgentState
from file_processor import process_files
from output_generator import to_csv, to_excel, to_pdf, to_png

# ── Constants ─────────────────────────────────────────────────────────────────

WELCOME_MSG = """\
Welcome to **Sony Business Intelligence Chatbot**! 🤖

您好！歡迎使用 **Sony 商業智慧聊天機器人**！
ソニービジネスインテリジェンスへようこそ！

---
Ask questions in **English**, **繁體中文**, or **日本語** — I'll reply in the same language.

You can also **upload files** (CSV, Excel, PDF, Word) for analysis.
Query results are automatically available as **CSV / Excel** downloads.

> Add keywords like *"chart"* / *"圖表"* / *"グラフ"* for a PNG visualization,
> or *"report"* / *"報告"* / *"レポート"* for a PDF export.
"""

_CHART_KEYWORDS = [
    "chart", "graph", "plot", "visual", "visualize", "趨勢圖", "圖表", "圖",
    "グラフ", "可視化", "チャート",
]
_REPORT_KEYWORDS = [
    "report", "pdf", "export", "報告", "匯出", "レポート", "エクスポート",
]


def _wants_chart(q: str) -> bool:
    q_lower = q.lower()
    return any(kw in q_lower for kw in _CHART_KEYWORDS)


def _wants_report(q: str) -> bool:
    q_lower = q.lower()
    return any(kw in q_lower for kw in _REPORT_KEYWORDS)


# ── Lifecycle ─────────────────────────────────────────────────────────────────

@cl.on_chat_start
async def start():
    msg = cl.Message(content="Initializing connection to Databricks… ⏳")
    await msg.send()

    client = make_mcp_client()
    tools = await client.get_tools()
    graph = build_graph(tools)

    # Store both client and graph; client must stay alive to keep MCP subprocess running
    cl.user_session.set("client", client)
    cl.user_session.set("graph", graph)

    msg.content = WELCOME_MSG
    await msg.update()


@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")
    if graph is None:
        await cl.Message(content="Session error — please refresh the page.").send()
        return

    # 1. Parse any uploaded files
    file_context = await process_files(message.elements)

    # 2. Augment question with file context
    question = message.content
    if file_context:
        question = f"{question}\n\n[Uploaded file content]:\n{file_context}"

    # 3. Show thinking placeholder
    thinking_msg = cl.Message(content="Thinking… ⏳")
    await thinking_msg.send()

    # 4. Run LangGraph agent
    try:
        result: AgentState = await graph.ainvoke({
            "messages": [HumanMessage(content=question)],
            "user_question": question,
            "tool_results": [],
            "think_answer": "",
            "judge_feedback": "",
            "iteration_count": 0,
            "final_answer": "",
            "is_complete": False,
        })
    except Exception as exc:
        thinking_msg.content = f"❌ Agent error: {exc}"
        await thinking_msg.update()
        return

    answer = result.get("final_answer", "")
    tool_results = result.get("tool_results", [])
    iterations = result.get("iteration_count", 1)

    # 5. Build response text (include iteration info as a subtle footer)
    footer = f"\n\n---\n*{iterations} iteration(s) | {len(tool_results)} tool call(s)*"
    thinking_msg.content = answer + footer

    # 6. Build downloadable attachments
    elements = []

    if tool_results:
        csv_bytes = to_csv(tool_results)
        xlsx_bytes = to_excel(tool_results)
        elements += [
            cl.File(name="results.csv", content=csv_bytes, display="inline"),
            cl.File(name="results.xlsx", content=xlsx_bytes, display="inline"),
        ]

    if _wants_chart(question) and tool_results:
        try:
            png_bytes = to_png(tool_results, question=message.content)
            elements.append(cl.Image(name="chart.png", content=png_bytes, display="inline"))
        except Exception:
            pass  # chart generation is best-effort

    if _wants_report(question):
        try:
            pdf_bytes = to_pdf(message.content, answer, tool_results)
            elements.append(cl.File(name="report.pdf", content=pdf_bytes, display="inline"))
        except Exception:
            pass

    thinking_msg.elements = elements
    await thinking_msg.update()
