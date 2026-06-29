# FPT-FAI AI 聊天機器人 — Databricks Demo

以 Databricks 為基礎的端到端 AI 系統。  
使用者透過 Chainlit 聊天介面以自然語言提問，訊息經由 LangGraph 多代理系統處理後，透過 MCP Server 查詢 Databricks，最終回傳結構化答案並附帶可下載的資料檔案。

![架構圖](<FPT_databricks+agentic AI_architecture.png>)

---

## 目錄

1. [語意層 (Semantic Layer)](#語意層-semantic-layer)
2. [MCP Server](#mcp-server)
3. [多代理系統 (Multiple AI Agents)](#多代理系統-multiple-ai-agents)
4. [前端介面 (Front End)](#前端介面-front-end)
5. [LangSmith 追蹤](#langsmith-追蹤)

---

## 語意層 (Semantic Layer)

**位置：** `sql_dlt.sql` / `pyspark_dlt.py` · `semantic_model.yml`

以 **Delta Live Tables (DLT)** 構建、由 **Unity Catalog** 管理的四層 Lakehouse 資料管道。

```
原始 CSV
  └─► Bronze   (demo.bronze)     — 外部資料表，透過 Databricks UI 匯入
        └─► Silver  (demo.silver)    — DLT：清洗、去重、驗證
              └─► Gold    (demo.golden)   — DLT：月度聚合
                    └─► Diamond (demo.diamond)  — 供 AI 使用的語意資料表
```

| 層級 | 資料表 | 功能說明 |
|------|--------|----------|
| Silver | `dim_customers` | 國家名稱標準化、Email 驗證、去重 |
| Silver | `fct_orders` | 日期格式統一、過濾無效金額 |
| Silver | `fct_orders_extended` | 訂單與客戶的串流-靜態 Join |
| Gold | `agg_customer_monthly_stats` | 每位客戶的月度訂單數與營收 |
| Diamond | `sem_customer_transaction_summary` | 每位客戶的月度統計（AOV、訂單數、金額） |
| Diamond | `sem_regional_monthly_aov` | 各國各月份的平均訂單金額（AOV） |

`semantic_model.yml` 在 Diamond 層之上定義業務友好的指標與維度說明，讓 **Databricks AI/BI Genie** 能直接以自然語言回答問題。

---

## MCP Server

**位置：** `mcp_server/mcp_server.py` · `databricks_query.py`

以 **FastMCP**（stdio transport）實作的 MCP Server，對任何相容的 MCP 客戶端公開三個工具。  
`databricks_query.py` 提供底層的 Databricks SQL 連線函式。

### 工具清單

| 工具 | 說明 | 主要參數 |
|------|------|----------|
| `get_customer_transaction_summary` | 從 Diamond 層查詢每位客戶的月度統計 | `customer_ids`、`customer_names`、`months` |
| `get_regional_monthly_aov` | 從 Diamond 層查詢各地區各月份的 AOV | `countries`、`months` |
| `query_data_with_natural_language` | 以 Claude Haiku 將自然語言轉為 SQL，再查詢 Databricks | `question`（自由文字） |

### 呼叫鏈

```
MCP 客戶端
  └─► mcp_server.py  (FastMCP, stdio)
        ├─► get_customer_transaction_summary
        │     └─► databricks_query._query_customer()  →  Databricks SQL Warehouse
        ├─► get_regional_monthly_aov
        │     └─► databricks_query._query_aov()       →  Databricks SQL Warehouse
        └─► query_data_with_natural_language
              ├─► _generate_sql()   →  Claude Haiku（自然語言 → SQL）
              ├─► _validate_sql()   （封鎖 DDL / 多重陳述句）
              └─► _run_query()      →  Databricks SQL Warehouse
```

---

## 多代理系統 (Multiple AI Agents)

**位置：** `agent/`

以 **LangGraph** `StateGraph` 實作的兩個代理，組成 PASS / FAIL 回饋迴圈（最多 3 次迭代）。

### 代理說明

| 代理 | 模型 | 職責 |
|------|------|------|
| Think Agent（`think_agent.py`） | claude-sonnet-4-6 | 呼叫 MCP 工具、整合資料並產生業務回答 |
| Judge Agent（`judge_agent.py`） | claude-haiku-4-5-20251001 | 評估回答品質，回傳 PASS 或 FAIL 並附帶意見 |

### 狀態（`state.py`）

`AgentState` 包含：`messages`、`user_question`、`tool_results`、`think_answer`、`judge_feedback`、`iteration_count`、`final_answer`、`is_complete`。

### 呼叫鏈

```
run_agent.py  /  chainlit_app.py
  └─► agent/mcp_client.py   make_mcp_client()   （MultiServerMCPClient，stdio 子程序）
        └─► agent/graph.py  build_graph(tools)   （StateGraph）
              ├─► think 節點（create_think_node）
              │     ├─► Claude Sonnet  bind_tools(mcp_tools)
              │     └─► tool.ainvoke()  →  MCP Server  →  Databricks
              └─► judge 節點（judge_node）
                    ├─► Claude Haiku  → 回傳 JSON {"verdict": "PASS"|"FAIL", "feedback": "..."}
                    └─► route_after_judge()
                          ├─► PASS  →  END（設定 final_answer）
                          ├─► FAIL  →  think（注入意見，重新嘗試）
                          └─► 迭代次數 >= 3  →  END（強制完成）
```

---

## 前端介面 (Front End)

**位置：** `front_end/`

以 **Chainlit** 構建的聊天介面，支援多語言與檔案上傳/下載。

### 功能特色

| 功能 | 說明 |
|------|------|
| **多語言** | 自動偵測用戶語言：繁體中文 / 英文 / 日文 |
| **檔案上傳** | 支援 CSV、Excel、PDF、Word — 內容解析後注入為代理上下文 |
| **檔案下載** | 每次工具呼叫後自動將查詢結果匯出為 CSV 與 Excel |
| **互動圖表** | Plotly 圖表（關鍵字觸發：*chart / 圖表 / グラフ*） |
| **PDF 報告** | 關鍵字觸發（*report / 報告 / レポート*），包含問題、答案與資料表 |

### 主要模組

| 檔案 | 職責 |
|------|------|
| `chainlit_app.py` | 對話生命週期管理、訊息處理、元素組合 |
| `file_processor.py` | `process_files()` — 解析上傳檔案為純文字 |
| `output_generator.py` | `to_csv()`、`to_excel()`、`to_pdf()` — 從 `tool_results` 產生可下載的位元組 |

### 呼叫鏈

```
使用者訊息（Chainlit @on_message）
  └─► file_processor.process_files()          （解析上傳檔案 → 文字上下文）
        └─► graph.ainvoke(AgentState)          （LangGraph，附 LangSmith RunnableConfig）
              └─► [Think → Judge 迴圈]
                    └─► tool_results[]         （累積的 MCP 回應）
                          ├─► output_generator.to_csv()    →  public/temp_files/
                          ├─► output_generator.to_excel()  →  public/temp_files/
                          ├─► _build_plotly()              →  cl.Plotly 元素
                          └─► output_generator.to_pdf()    →  public/temp_files/
```

---

## LangSmith 追蹤

**位置：** `.env`（環境變數） · `front_end/chainlit_app.py`（RunnableConfig）

LangGraph 與 LangChain 內建 LangSmith 追蹤功能，**無需修改程式碼**，只要設定三個環境變數即可啟用。

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=ls__xxxxxxxx
LANGCHAIN_PROJECT=fpt-fai-ai-chatbot
```

每則聊天訊息在 LangSmith 產生一筆根追蹤，包含巢狀的子節點：

```
[使用者問題]  （根 run）
  └─► LangGraph
        ├─► think（第 1 次迭代）
        │     ├─► ChatAnthropic  claude-sonnet-4-6   ← Token 用量
        │     └─► MCP 工具呼叫                       ← 延遲、參數、輸出
        └─► judge（第 1 次迭代）
              └─► ChatAnthropic  claude-haiku-4-5    ← Token 用量、評判結果
```

`chainlit_app.py` 中的 `RunnableConfig` 為每次執行附加 `session_id` metadata 與 `fpt-fai-ai-chatbot` 標籤，方便在 LangSmith 儀表板中依對話過濾及彙總費用。

---

## 環境變數設定

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

## 快速啟動

```bash
# 安裝前端相依套件
cd front_end && pip install -r requirements.txt

# 啟動 Chainlit
chainlit run front_end/chainlit_app.py --port 8000
```
