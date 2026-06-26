# CLAUDE.md — Databricks Demo Project Context

## Project Purpose

This project builds a **Lakehouse + Semantic Layer** on Databricks as the data foundation for a Sony AI chatbot system. The end goal is a Multi-Agent AI system that lets business users query enterprise data through natural language.

The architecture has two phases:
- **Phase 1**: Clean, structured data pipeline (Bronze → Silver → Gold → Diamond) with a semantic layer exposed via Unity Catalog and MCP query functions
- **Phase 2**: Multi-Agent AI system (Chainlit + LangGraph + MCP) that queries the semantic layer and answers business questions

---

## Repository Structure

| File | Layer | Description |
|------|-------|-------------|
| `raw_customer_profile.csv` | Source | 48 customer records with intentional dirty data (duplicate IDs, inconsistent country names, missing emails) |
| `raw_order_transactions.csv` | Source | 1,000 order records with mixed date formats, negative amounts, orphan customer C999 |
| `sql_dlt.sql` | Silver→Diamond | Full DLT pipeline in SQL |
| `pyspark_dlt.py` | Silver→Diamond | Full DLT pipeline in PySpark |
| `semantic_model.yml` | Diamond | Unity Catalog semantic layer definition for AI/BI Genie |
| `databricks_query.py` | Query | Python query functions for MCP server integration |
| `drop_table.sql.dbquery.ipynb` | Utility | Resets Silver/Gold/Diamond tables for re-running demos |

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

## Query Functions (`databricks_query.py`)

Two functions designed to be registered as MCP server tools:

**`get_customer_transaction_summary(customer_ids, customer_names, months)`**
- All params optional; omit `months` to get all-time totals
- Filters by customer ID or name (OR logic)
- Returns: `customer_id, customer_name, country, order_month, total_order_count, total_order_amount, avg_order_value`

**`get_regional_monthly_aov(countries, months)`**
- All params optional
- Returns: `country, order_month, total_order_count, total_order_amount, aov`

Connection via env vars: `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN`

---

## Semantic Layer (`semantic_model.yml`)

Unity Catalog YAML defining metrics and dimensions over `demo.diamond` tables.
Compatible with Databricks AI/BI Genie for natural language querying.
Includes sample questions in Traditional Chinese for demo purposes.

---

## Completed Items

- [x] Bronze layer — external tables registered in Unity Catalog via Databricks UI
- [x] Silver layer — `dim_customers`, `fct_orders`, `fct_orders_extended` (SQL + PySpark)
- [x] Gold layer — `agg_customer_monthly_stats` (SQL + PySpark)
- [x] Diamond layer — `sem_customer_transaction_summary`, `sem_regional_monthly_aov` (SQL + PySpark)
- [x] Unity Catalog semantic model YAML (`semantic_model.yml`)
- [x] MCP query functions (`databricks_query.py`)
- [x] GitHub repo connected to Databricks; all pipeline files pushed

---

## Future Development (Phase 2)

- [ ] **MCP Server** — Wrap `databricks_query.py` functions as MCP tools using `FastMCP`; register as a running server
- [ ] **Chainlit frontend** — Chat UI for business users to ask natural language questions
- [ ] **LangGraph agent** — Orchestration layer that routes questions → selects the right MCP tool → formats the response
- [ ] **Multiple agents** — Potentially: a Router Agent, a Data Query Agent, a Summarization Agent
- [ ] **LangSmith integration** — Track, monitor, and optimize agent performance
- [ ] **AI/BI Genie** — Register `semantic_model.yml` in Unity Catalog; demo natural language querying directly in Databricks

---

## Notes for Claude

- The DLT pipeline files (`sql_dlt.sql`, `pyspark_dlt.py`) are synced to GitHub and pulled into Databricks via Git integration. After editing, always push to GitHub so Databricks picks up the changes.
- The `demo.bronze` tables are **not** created by DLT — they are manually registered in the Databricks UI as external tables pointing to CSV files. This is intentional to demo the ingestion step.
- Both SQL and PySpark versions of the pipeline are maintained in parallel; keep them in sync when making changes.
- Default repo: `Paul60209/databricks_demo`, branch: `main`
- The git workflow requires running `git push` from the user's local Terminal (sandbox network cannot reach GitHub directly).
