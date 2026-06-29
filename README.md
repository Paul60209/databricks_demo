# FPT-FAI AI Chatbot — Databricks Demo

An end-to-end AI system built on Databricks.  
Natural language queries flow from a Chainlit chat UI through a LangGraph multi-agent system, reach Databricks via an MCP server, and return structured answers with downloadable data files.

![Architecture](<FPT_databricks+agentic AI_architecture.png>)

---

## Table of Contents

1. [Semantic Layer](#semantic-layer)
2. [MCP Server](#mcp-server)
3. [Multiple AI Agents](#multiple-ai-agents)
4. [Front End](#front-end)
5. [LangSmith](#langsmith)

---

## Semantic Layer

**Location:** `sql_dlt.sql` / `pyspark_dlt.py` · `semantic_model.yml`

A four-layer Lakehouse pipeline built with **Delta Live Tables (DLT)** and managed by **Unity Catalog**.

```
Raw CSV
  └─► Bronze   (demo.bronze)     — external tables, ingested via Databricks UI
        └─► Silver  (demo.silver)    — DLT: clean, deduplicate, validate
              └─► Gold    (demo.golden)   — DLT: monthly aggregation
                    └─► Diamond (demo.diamond)  — semantic tables for AI consumption
```

| Layer | Table | Role |
|-------|-------|------|
| Silver | `dim_customers` | Country standardisation, email validation, dedup |
| Silver | `fct_orders` | Date format unification, drop invalid amounts |
| Silver | `fct_orders_extended` | Stream-static join of orders + customers |
| Gold | `agg_customer_monthly_stats` | Monthly revenue & order count per customer |
| Diamond | `sem_customer_transaction_summary` | Per-customer monthly stats (AOV, count, amount) |
| Diamond | `sem_regional_monthly_aov` | AOV by country and month |

`semantic_model.yml` registers business-friendly metric and dimension descriptions over the Diamond layer, enabling **Databricks AI/BI Genie** to answer natural language questions directly.

---

## MCP Server

**Location:** `mcp_server/mcp_server.py` · `databricks_query.py`

A **FastMCP** server (stdio transport) that exposes three tools to any MCP-compatible client.  
`databricks_query.py` provides the underlying Databricks SQL connector functions.

### Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `get_customer_transaction_summary` | Per-customer monthly stats from Diamond layer | `customer_ids`, `customer_names`, `months` |
| `get_regional_monthly_aov` | AOV by country and month from Diamond layer | `countries`, `months` |
| `query_data_with_natural_language` | Text-to-SQL via Claude Haiku → Databricks | `question` (free text) |

### Call chain

```
MCP Client
  └─► mcp_server.py  (FastMCP, stdio)
        ├─► get_customer_transaction_summary
        │     └─► databricks_query._query_customer()  →  Databricks SQL Warehouse
        ├─► get_regional_monthly_aov
        │     └─► databricks_query._query_aov()       →  Databricks SQL Warehouse
        └─► query_data_with_natural_language
              ├─► _generate_sql()   →  Claude Haiku  (text → SQL)
              ├─► _validate_sql()   (block DDL / multi-statement)
              └─► _run_query()      →  Databricks SQL Warehouse
```

---

## Multiple AI Agents

**Location:** `agent/`

A **LangGraph** `StateGraph` with two agents in a PASS / FAIL feedback loop (max 3 iterations).

### Agents

| Agent | Model | Role |
|-------|-------|------|
| Think Agent (`think_agent.py`) | claude-sonnet-4-6 | Calls MCP tools, synthesises a business answer |
| Judge Agent (`judge_agent.py`) | claude-haiku-4-5-20251001 | Evaluates the answer; returns PASS or FAIL with feedback |

### State (`state.py`)

`AgentState` carries: `messages`, `user_question`, `tool_results`, `think_answer`, `judge_feedback`, `iteration_count`, `final_answer`, `is_complete`.

### Call chain

```
run_agent.py  /  chainlit_app.py
  └─► agent/mcp_client.py   make_mcp_client()   (MultiServerMCPClient, stdio subprocess)
        └─► agent/graph.py  build_graph(tools)   (StateGraph)
              ├─► think  node  (create_think_node)
              │     ├─► Claude Sonnet  bind_tools(mcp_tools)
              │     └─► tool.ainvoke()  →  MCP Server  →  Databricks
              └─► judge  node  (judge_node)
                    ├─► Claude Haiku  → verdict JSON  {"verdict": "PASS"|"FAIL", "feedback": "..."}
                    └─► route_after_judge()
                          ├─► PASS  →  END  (set final_answer)
                          ├─► FAIL  →  think  (inject feedback, retry)
                          └─► iteration >= 3  →  END  (force complete)
```

---

## Front End

**Location:** `front_end/`

A **Chainlit** chat UI with multilingual support and file I/O.

### Features

| Feature | Details |
|---------|---------|
| **Languages** | Auto-detected from user input: Traditional Chinese / English / Japanese |
| **File upload** | CSV, Excel, PDF, Word — content extracted and injected as agent context |
| **File download** | Query results auto-exported as CSV and Excel after every tool call |
| **Charts** | Plotly interactive charts (keyword-triggered: *chart / 圖表 / グラフ*) |
| **PDF report** | Keyword-triggered export (*report / 報告 / レポート*) including question, answer, and data table |

### Key modules

| File | Role |
|------|------|
| `chainlit_app.py` | Session lifecycle, message handler, element assembly |
| `file_processor.py` | `process_files()` — parses uploaded files into plain text |
| `output_generator.py` | `to_csv()`, `to_excel()`, `to_pdf()` — build downloadable bytes from `tool_results` |

### Call chain

```
User message  (Chainlit @on_message)
  └─► file_processor.process_files()          (parse uploads → text context)
        └─► graph.ainvoke(AgentState)          (LangGraph, with LangSmith RunnableConfig)
              └─► [Think → Judge loop]
                    └─► tool_results[]         (accumulated MCP responses)
                          ├─► output_generator.to_csv()    →  public/temp_files/
                          ├─► output_generator.to_excel()  →  public/temp_files/
                          ├─► _build_plotly()              →  cl.Plotly element
                          └─► output_generator.to_pdf()    →  public/temp_files/
```

---

## LangSmith

**Location:** `.env` (env vars) · `front_end/chainlit_app.py` (RunnableConfig)

LangGraph and LangChain have **built-in LangSmith tracing** — no code decoration needed.  
Setting three environment variables activates full tracing automatically.

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__xxxxxxxx
LANGCHAIN_PROJECT=fpt-fai-ai-chatbot
```

Each chat message produces one root trace in LangSmith with nested spans:

```
[user question]  (root run)
  └─► LangGraph
        ├─► think  (iteration 1)
        │     ├─► ChatAnthropic  claude-sonnet-4-6   ← token counts
        │     └─► MCP tool calls                     ← latency, args, output
        └─► judge  (iteration 1)
              └─► ChatAnthropic  claude-haiku-4-5    ← token counts, verdict
```

`RunnableConfig` in `chainlit_app.py` attaches `session_id` metadata and `fpt-fai-ai-chatbot` tag to every run, enabling per-session filtering and cost aggregation in the LangSmith dashboard.

---

## Environment Variables

```bash
# Databricks
DATABRICKS_HOST=adb-xxxxxxxxxxxx.xx.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxxxxxxxxxxxxxx
DATABRICKS_TOKEN=your_personal_access_token

# Anthropic
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx

# LangSmith
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__xxxxxxxx
LANGCHAIN_PROJECT=fpt-fai-ai-chatbot
```

## Quick Start

```bash
# Install front-end dependencies
cd front_end && pip install -r requirements.txt

# Start Chainlit
chainlit run front_end/chainlit_app.py --port 8000
```
