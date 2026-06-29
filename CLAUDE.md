# CLAUDE.md — Databricks Demo Project Context

## Project Purpose

This project builds a **Lakehouse + Semantic Layer** on Databricks as the data foundation for a FPT-FAI AI chatbot system. The end goal is a Multi-Agent AI system that lets business users query enterprise data through natural language.

The architecture has two phases:
- **Phase 1**: Clean, structured data pipeline (Bronze → Silver → Gold → Diamond) with a semantic layer exposed via Unity Catalog and MCP query functions
- **Phase 2**: Multi-Agent AI system (Chainlit + LangGraph + MCP) that queries the semantic layer and answers business questions

**Phase 2 is now complete and operational.**

---

## Repository Structure

| Path | Layer / Role | Description |
|------|-------------|-------------|
| `raw_customer_profile.csv` | Source | 48 customer records with intentional dirty data |
| `raw_order_transactions.csv` | Source | 1,000 order records with mixed date formats, negative amounts |
| `sql_dlt.sql` | Silver→Diamond | Full DLT pipeline in SQL |
| `pyspark_dlt.py` | Silver→Diamond | Full DLT pipeline in PySpark |
| `semantic_model.yml` | Diamond | Unity Catalog semantic layer definition for AI/BI Genie |
| `databricks_query.py` | Query | Base Databricks SQL connector functions used by MCP server |
| `drop_table.sql.dbquery.ipynb` | Utility | Resets Silver/Gold/Diamond tables for re-running demos |
| `mcp_server/mcp_server.py` | MCP | FastMCP server exposing 3 tools over stdio |
| `agent/state.py` | Agent | AgentState TypedDict definition |
| `agent/mcp_client.py` | Agent | MultiServerMCPClient factory with explicit env var passing |
| `agent/think_agent.py` | Agent | Think Agent (claude-sonnet-4-6) — ReAct loop, calls MCP tools |
| `agent/judge_agent.py` | Agent | Judge Agent (claude-haiku-4-5-20251001) — PASS/FAIL evaluator |
| `agent/graph.py` | Agent | LangGraph StateGraph: think → judge → conditional routing |
| `run_agent.py` | CLI | CLI entry point for testing agent without Chainlit |
| `front_end/chainlit_app.py` | Frontend | Chainlit app: session lifecycle, message handler, file elements |
| `front_end/file_processor.py` | Frontend | Parses uploaded CSV/Excel/PDF/Word into plain text |
| `front_end/output_generator.py` | Frontend | Generates CSV/Excel/PDF bytes from tool_results |
| `front_end/FPT_logo.png` | Branding | FPT logo source file (400×400 PNG) |
| `public/temp_files/` | Frontend | Temp dir for downloadable files; served as Chainlit static files |
| `public/FPT_logo.png` | Branding | FPT logo served as Chainlit static asset |
| `public/custom.css` | Frontend | Custom CSS: expands `#header` to 96px for logo display |
| `public/custom.js` | Frontend | Injects FPT logo (80px) into Chainlit `#header` via JS |
| `chainlit.md` | Frontend | Chainlit readme/info panel — tri-lingual (EN→JP→ZH), FPT logo inline |
| `front_end/chainlit.md` | Frontend | Same as above (Chainlit reads from working directory) |
| `FPT_databricks+agentic AI_architecture.png` | Docs | Architecture diagram — FPT-FAI version |
| `README.md` | Docs | English README (GitHub default) |
| `README_CN.md` | Docs | Traditional Chinese README |
| `README_JP.md` | Docs | Japanese README |

---

## Data Pipeline (Unity Catalog: `demo` catalog)

### Bronze (`demo.bronze`) — External tables, ingested via Databricks UI
- `raw_customer_profile`
- `raw_order_transactions`

### Silver (`demo.silver`) — DLT managed tables
- `dim_customers` — LIVE TABLE: country standardization (tw/TW/Taiwan → Taiwan), email validation, dedup by latest `created_ts`
- `fct_orders` — STREAMING TABLE: date format unification (3 formats → DATE), drops rows where `amount <= 0`
- `fct_orders_extended` — STREAMING TABLE: stream-static join of orders + customers

### Gold (`demo.golden`) — DLT managed tables
- `agg_customer_monthly_stats` — LIVE TABLE: monthly aggregation by customer × country

### Diamond (`demo.diamond`) — Semantic layer, DLT managed tables
- `sem_customer_transaction_summary` — per-customer monthly stats (count, amount, AOV)
- `sem_regional_monthly_aov` — AOV aggregated by country × month

---

## MCP Server (`mcp_server/mcp_server.py`)

FastMCP server (stdio transport). Three tools:

| Tool | Description |
|------|-------------|
| `get_customer_transaction_summary` | Typed query on `demo.diamond`; params: `customer_ids`, `customer_names`, `months` (all optional) |
| `get_regional_monthly_aov` | Typed query on `demo.diamond`; params: `countries`, `months` (all optional) |
| `query_data_with_natural_language` | Text-to-SQL via Claude Haiku → Databricks; param: `question` |

`databricks_query.py` provides the underlying `_query_customer()`, `_query_aov()`, `_run_query()` functions.  
The MCP server subprocess is spawned by `agent/mcp_client.py` and must receive env vars explicitly (see known issues below).

---

## LangGraph Multi-Agent System (`agent/`)

**Think Agent** (`claude-sonnet-4-6`) — inner ReAct loop (max 5 rounds), calls MCP tools, synthesises business answer.  
**Judge Agent** (`claude-haiku-4-5-20251001`) — evaluates Think's answer; returns `{"verdict": "PASS"|"FAIL", "feedback": "..."}`.  
**Graph** (`graph.py`) — `think → judge → route_after_judge`; loops back on FAIL, exits on PASS or ≥ 3 iterations.

`AgentState` fields: `messages`, `user_question`, `tool_results`, `think_answer`, `judge_feedback`, `iteration_count`, `final_answer`, `is_complete`.

---

## Chainlit Frontend (`front_end/`)

Run with:
```bash
source front_end/.venv/bin/activate
chainlit run front_end/chainlit_app.py --port 8000
```

Features:
- **Multilingual**: auto-detects Traditional Chinese / English / Japanese from user input
- **File upload**: CSV, Excel, PDF, Word — extracted as plain text and injected as agent context
- **File download**: CSV + Excel auto-generated after every tool call; PDF on request (*"report"*)
- **Charts**: Plotly interactive chart on request (*"chart / 圖表 / グラフ"*)
- Files are written to `public/temp_files/` and served via Chainlit static URL `/public/temp_files/...`

---

## LangSmith Tracing

Enabled via env vars — no code changes needed:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__xxxxxxxx
LANGCHAIN_PROJECT=fpt-fai-ai-chatbot
```

Each `graph.ainvoke()` call is one root trace. `RunnableConfig` in `chainlit_app.py` attaches `session_id` metadata and `fpt-fai-ai-chatbot` tag.

**Important:** Judge Agent spans appear as a **sibling** of Think Agent in the LangSmith trace tree, NOT nested inside Think. They do NOT appear in the `messages` output (Judge only updates `is_complete`, `final_answer`, `judge_feedback`). To see Judge, expand the LangGraph span tree in LangSmith's timeline/trace view.

---

## Completed Items

- [x] Bronze layer — external tables registered in Unity Catalog via Databricks UI
- [x] Silver layer — `dim_customers`, `fct_orders`, `fct_orders_extended` (SQL + PySpark)
- [x] Gold layer — `agg_customer_monthly_stats` (SQL + PySpark)
- [x] Diamond layer — `sem_customer_transaction_summary`, `sem_regional_monthly_aov` (SQL + PySpark)
- [x] Unity Catalog semantic model YAML (`semantic_model.yml`)
- [x] MCP query functions (`databricks_query.py`)
- [x] GitHub repo connected to Databricks; all pipeline files pushed
- [x] **MCP Server** — FastMCP with 3 tools (typed queries + text2SQL)
- [x] **LangGraph agent** — Think + Judge two-agent PASS/FAIL loop
- [x] **Chainlit frontend** — multilingual, file upload/download, Plotly charts
- [x] **LangSmith integration** — full trace with session metadata and token tracking
- [x] **Multilingual README** — EN (`README.md`), 繁體中文 (`README_CN.md`), 日本語 (`README_JP.md`)
- [x] **FPT-FAI branding** — removed all Sony references; repo is now client-agnostic (branch: `feature/fpt-demo` → merged to `main`)

---

## Remaining / Future

- [ ] **AI/BI Genie** — Register `semantic_model.yml` in Unity Catalog; demo natural language querying directly in Databricks
- [ ] **Judge span visibility** — Optionally add `run_name` to Judge's `llm.ainvoke()` config for clearer LangSmith labelling

---

## Known Issues & Workarounds

### MCP subprocess env vars
`MultiServerMCPClient` spawns the MCP server as a subprocess which does **not** inherit parent env vars automatically. Must pass explicitly:
```python
"env": {k: v for k in ["DATABRICKS_HOST", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN",
                        "ANTHROPIC_API_KEY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"]
        if (v := os.environ.get(k))}
```

### MCP tool result format
`tool.ainvoke()` returns a list of MCP content blocks. After `str()` conversion it looks like:
```
"[{'type': 'text', 'text': '[{actual JSON}]', 'id': 'lc_...'}]"
```
**Must use `ast.literal_eval()` first, then `json.loads(parsed[0]["text"])`** — `json.loads()` directly on this string will fail silently and produce empty DataFrames. This is handled in `output_generator._extract_json()` and `chainlit_app._build_plotly()`.

### Chainlit file downloads (no cloud storage)
Chainlit 2.x requires a cloud storage backend (S3/GCS/Azure) for `cl.File(content=bytes)`. Without it, `url` is null → JS crash (`Cannot read properties of null (reading 'startsWith')`).  
**Workaround**: write files to `public/temp_files/` and reference via `cl.File(url="/public/temp_files/...")`. Chainlit serves `public/` as static files automatically.

### langchain-mcp-adapters 0.1.x
`MultiServerMCPClient` cannot be used as an `async with` context manager (removed in 0.1.0).  
**Use**: `tools = await client.get_tools()` directly. Keep `client` alive in `cl.user_session` to prevent subprocess from being killed.

---

## Chainlit UI Customisation (`public/`)

| File | Purpose |
|------|---------|
| `public/custom.css` | Expands `#header` to 96px height to accommodate the 80px FPT logo |
| `public/custom.js` | On page load, queries `#header` and prepends an 80px FPT logo `<img>` |
| `public/FPT_logo.png` | Static asset served at `/public/FPT_logo.png` |

`.chainlit/config.toml` key settings:
```toml
logo_file_url = "/public/FPT_logo.png"      # avatar in chat messages
default_avatar_file_url = "/public/FPT_logo.png"
avatar_size = 48
custom_css = "/public/custom.css"
custom_js = "/public/custom.js"
unsafe_allow_html = true                     # required for inline HTML in chainlit.md
```

`chainlit.md` format: FPT logo (via CSS `background-image` on `<span>` — avoids Chainlit's 16:9 media card wrapping) + title on same line, followed by three language sections in order EN → JP → ZH.

> **Why `<span>` not `<img>`**: Chainlit's markdown parser detects `<img>` tags and wraps them in a Radix aspect-ratio card (16:9). Using a `<span>` with `background:url(...)` bypasses this and allows true inline display.

---

## Notes for Claude

- The DLT pipeline files (`sql_dlt.sql`, `pyspark_dlt.py`) are synced to GitHub and pulled into Databricks via Git integration. After editing, always push to GitHub so Databricks picks up the changes.
- The `demo.bronze` tables are **not** created by DLT — they are manually registered in the Databricks UI as external tables pointing to CSV files. This is intentional to demo the ingestion step.
- Both SQL and PySpark versions of the pipeline are maintained in parallel; keep them in sync when making changes.
- Default repo: `Paul60209/databricks_demo`, branch: `main`
- The git workflow requires running `git push` from the user's local Terminal (sandbox network cannot reach GitHub directly).
- Three separate `.venv` directories exist: `front_end/.venv`, `agent/.venv`, `mcp_server/.venv`. Chainlit must be run from `front_end/.venv`.
- `public/temp_files/` is in `.gitignore`; only `.gitkeep` is committed to preserve the directory.
- The Databricks query functions run **locally** (in the MCP server subprocess), not on Databricks. Only the SQL execution happens remotely on the Databricks SQL Warehouse.
