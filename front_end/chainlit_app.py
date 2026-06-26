"""
Sony BI Chatbot — Chainlit Frontend

Run:
    chainlit run front_end/chainlit_app.py --port 8000
"""

import sys
import uuid
import json
from pathlib import Path

# Allow importing agent/ from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

import chainlit as cl
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from agent.mcp_client import make_mcp_client
from agent.graph import build_graph
from agent.state import AgentState
from file_processor import process_files
from output_generator import to_csv, to_excel, to_pdf
import plotly.graph_objects as go
import pandas as pd

_TEMP_DIR = Path(__file__).parent.parent / "public" / "temp_files"
_TEMP_DIR.mkdir(parents=True, exist_ok=True)

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
    cl.user_session.set("session_id", str(uuid.uuid4()))

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

    # 4. Run LangGraph agent (RunnableConfig enables LangSmith tracing with session metadata)
    langsmith_config = RunnableConfig(
        run_name=message.content[:60],
        metadata={
            "session_id": cl.user_session.get("session_id"),
            "user_question": message.content,
        },
        tags=["sony-bi-chatbot"],
    )
    try:
        result: AgentState = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=question)],
                "user_question": question,
                "tool_results": [],
                "think_answer": "",
                "judge_feedback": "",
                "iteration_count": 0,
                "final_answer": "",
                "is_complete": False,
            },
            config=langsmith_config,
        )
    except Exception as exc:
        thinking_msg.content = f"❌ Agent error: {exc}"
        await thinking_msg.update()
        return

    answer = result.get("final_answer", "")
    tool_results = result.get("tool_results", [])
    iterations = result.get("iteration_count", 1)

    # 5. Remove thinking placeholder
    await thinking_msg.remove()

    # 6. Build elements — write files to public/temp_files/ so Chainlit can serve via URL
    uid = uuid.uuid4().hex[:8]
    elements = []

    if tool_results:
        csv_path  = _TEMP_DIR / f"results_{uid}.csv"
        xlsx_path = _TEMP_DIR / f"results_{uid}.xlsx"
        csv_path.write_bytes(to_csv(tool_results))
        xlsx_path.write_bytes(to_excel(tool_results))
        elements += [
            cl.File(name="results.csv",  url=f"/public/temp_files/results_{uid}.csv",  display="inline"),
            cl.File(name="results.xlsx", url=f"/public/temp_files/results_{uid}.xlsx", display="inline"),
        ]

    if _wants_chart(question) and tool_results:
        try:
            fig = _build_plotly(tool_results, question=message.content)
            elements.append(cl.Plotly(name="chart", figure=fig, display="inline"))
        except Exception:
            pass

    if _wants_report(question):
        try:
            pdf_path = _TEMP_DIR / f"report_{uid}.pdf"
            pdf_path.write_bytes(to_pdf(message.content, answer, tool_results))
            elements.append(cl.File(name="report.pdf", url=f"/public/temp_files/report_{uid}.pdf", display="inline"))
        except Exception:
            pass

    # 7. Send final answer + elements
    footer = f"\n\n---\n*{iterations} iteration(s) | {len(tool_results)} tool call(s)*"
    await cl.Message(content=answer + footer, elements=elements).send()


def _build_plotly(tool_results: list[dict], question: str = "") -> go.Figure:
    """Build a Plotly figure from tool_results."""
    import ast
    frames = []
    for item in tool_results:
        raw = item.get("result", "[]")
        try:
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "text" in parsed[0]:
                data = json.loads(parsed[0]["text"])
            else:
                data = parsed
        except Exception:
            try:
                data = json.loads(raw)
            except Exception:
                continue
        if isinstance(data, list) and data:
            frames.append(pd.DataFrame(data))
        elif isinstance(data, dict) and "data" in data:
            frames.append(pd.DataFrame(data["data"]))

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    title = question[:70] + ("…" if len(question) > 70 else "")

    if df.empty:
        return go.Figure().update_layout(title="No data")

    if "order_month" in df.columns:
        df["order_month"] = pd.to_datetime(df["order_month"], errors="coerce")
        df = df.sort_values("order_month")
        value_col = next((c for c in ["aov", "avg_order_value", "total_order_amount"] if c in df.columns), None)
        group_col = next((c for c in ["country", "customer_name"] if c in df.columns), None)
        fig = go.Figure()
        if value_col:
            if group_col:
                for label, grp in df.groupby(group_col):
                    fig.add_trace(go.Scatter(x=grp["order_month"], y=grp[value_col], mode="lines+markers", name=str(label)))
            else:
                fig.add_trace(go.Scatter(x=df["order_month"], y=df[value_col], mode="lines+markers"))
        fig.update_layout(title=title, xaxis_title="Month", yaxis_title=value_col or "")
    else:
        label_col = next((c for c in ["country", "customer_name", "customer_id"] if c in df.columns), df.columns[0])
        value_col = next((c for c in ["aov", "avg_order_value", "total_order_amount", "total_order_count"] if c in df.columns),
                         df.select_dtypes("number").columns[0] if not df.select_dtypes("number").empty else None)
        fig = go.Figure()
        if value_col:
            df_plot = df[[label_col, value_col]].dropna().head(15)
            fig.add_trace(go.Bar(x=df_plot[value_col], y=df_plot[label_col].astype(str), orientation="h"))
        fig.update_layout(title=title, xaxis_title=value_col or "", yaxis_autorange="reversed")

    return fig
