"""
MCP Server — Databricks Demo
=============================
Exposes three tools over stdio (FastMCP):
  1. get_customer_transaction_summary  — typed query on demo.diamond
  2. get_regional_monthly_aov          — typed query on demo.diamond
  3. query_data_with_natural_language  — text2SQL via Claude → Databricks

Environment variables required:
    DATABRICKS_HOST, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN
    ANTHROPIC_API_KEY
"""

import os
import sys
import json
import re

# Allow importing databricks_query from the repo root (parent directory)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic
from mcp.server.fastmcp import FastMCP
from databricks_query import (
    get_customer_transaction_summary as _query_customer,
    get_regional_monthly_aov as _query_aov,
    _run_query,
)

# ── Schema context injected into every text2SQL prompt ────────────────────────

SCHEMA_CONTEXT = """
Available Databricks tables (Unity Catalog: demo.*):

=== Silver layer ===
demo.silver.dim_customers
    customer_id VARCHAR, customer_name VARCHAR, email VARCHAR,
    country VARCHAR (values: Taiwan, Japan, United States, Unknown),
    created_ts TIMESTAMP

demo.silver.fct_orders
    order_id VARCHAR, customer_id VARCHAR, amount DOUBLE,
    status VARCHAR, order_date DATE

demo.silver.fct_orders_extended
    order_id VARCHAR, customer_id VARCHAR, amount DOUBLE,
    status VARCHAR, order_date DATE,
    customer_name VARCHAR, email VARCHAR, country VARCHAR

=== Gold layer ===
demo.golden.agg_customer_monthly_stats
    order_month TIMESTAMP (first day of month, e.g. 2025-01-01),
    country VARCHAR, customer_id VARCHAR, customer_name VARCHAR,
    total_order_count BIGINT, total_order_amount DOUBLE

=== Diamond layer (prefer these — pre-aggregated semantic tables) ===
demo.diamond.sem_customer_transaction_summary
    customer_id VARCHAR, customer_name VARCHAR, country VARCHAR,
    order_month TIMESTAMP, total_order_count BIGINT,
    total_order_amount DOUBLE, avg_order_value DOUBLE

demo.diamond.sem_regional_monthly_aov
    country VARCHAR, order_month TIMESTAMP,
    total_order_count BIGINT, total_order_amount DOUBLE, aov DOUBLE

Rules:
- DO NOT query demo.bronze tables.
- Prefer Diamond layer; use Silver/Gold only when Diamond lacks needed granularity.
- order_month is a TIMESTAMP (first day of the month).
- To filter by month string use: DATE_FORMAT(order_month, 'yyyy-MM') = '2025-01'
- Use standard Databricks SQL (Spark SQL dialect).
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

_FORBIDDEN = ["DROP", "DELETE", "UPDATE", "INSERT", "CREATE", "ALTER", "TRUNCATE", "MERGE"]


def _df_to_json(df) -> str:
    return json.dumps(df.to_dict(orient="records"), ensure_ascii=False, default=str)


def _validate_sql(sql: str) -> tuple[bool, str]:
    stripped = sql.strip()
    upper = stripped.upper()

    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return False, "SQL must start with SELECT or WITH"

    for kw in _FORBIDDEN:
        if re.search(rf"\b{kw}\b", upper):
            return False, f"Forbidden keyword: {kw}"

    if stripped.count(";") > 1:
        return False, "Multi-statement SQL is not allowed"

    return True, ""


def _generate_sql(question: str) -> str:
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        system=(
            "You are a Databricks SQL expert. "
            "Output only valid Databricks SQL — no markdown fences, no explanation.\n\n"
            + SCHEMA_CONTEXT
        ),
        messages=[{"role": "user", "content": f"Generate SQL for: {question}"}],
    )
    sql = response.content[0].text.strip()
    # Strip any residual ```sql ... ``` fences that the model might add
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip()


# ── FastMCP server ────────────────────────────────────────────────────────────

mcp = FastMCP("databricks-demo")


@mcp.tool()
def get_customer_transaction_summary(
    customer_ids: list[str] | None = None,
    customer_names: list[str] | None = None,
    months: list[str] | None = None,
) -> str:
    """
    Query per-customer monthly transaction stats from the Diamond layer.

    Args:
        customer_ids:   Filter by customer ID list, e.g. ["C001", "C002"]. Optional.
        customer_names: Filter by customer name list, e.g. ["John Doe"]. Optional.
                        Combined with customer_ids using OR logic.
        months:         Filter by month list in YYYY-MM format, e.g. ["2025-01"]. Optional.
                        Omit to get all-time totals collapsed into a single row per customer.

    Returns:
        JSON array with columns: customer_id, customer_name, country, order_month,
        total_order_count, total_order_amount, avg_order_value
    """
    try:
        df = _query_customer(
            customer_ids=customer_ids,
            customer_names=customer_names,
            months=months,
        )
        return _df_to_json(df)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def get_regional_monthly_aov(
    countries: list[str] | None = None,
    months: list[str] | None = None,
) -> str:
    """
    Query Average Order Value (AOV) by region and month from the Diamond layer.

    Args:
        countries: Filter by country list, e.g. ["Taiwan", "Japan"]. Optional.
        months:    Filter by month list in YYYY-MM format, e.g. ["2025-03"]. Optional.

    Returns:
        JSON array with columns: country, order_month,
        total_order_count, total_order_amount, aov
    """
    try:
        df = _query_aov(countries=countries, months=months)
        return _df_to_json(df)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def query_data_with_natural_language(question: str) -> str:
    """
    Answer a business question by generating SQL with Claude and running it on Databricks.

    Queries can target Silver, Gold, or Diamond layer tables. Bronze tables are excluded.
    The generated SQL is always returned in the response for transparency.

    Args:
        question: Natural language business question, e.g.
                  "Taiwan 地區 2025 年 Q1 的 AOV 趨勢"

    Returns:
        JSON object with keys:
            generated_sql  — the SQL Claude generated
            row_count      — number of result rows
            data           — array of result rows
        On error, returns JSON with an "error" key.
    """
    generated_sql = None
    try:
        generated_sql = _generate_sql(question)

        is_valid, reason = _validate_sql(generated_sql)
        if not is_valid:
            return json.dumps(
                {"error": f"SQL blocked: {reason}", "generated_sql": generated_sql},
                ensure_ascii=False,
            )

        df = _run_query(generated_sql)
        return json.dumps(
            {
                "generated_sql": generated_sql,
                "row_count": len(df),
                "data": json.loads(_df_to_json(df)),
            },
            ensure_ascii=False,
        )

    except anthropic.APIError as e:
        return json.dumps(
            {"error": f"Anthropic API error: {e}", "generated_sql": generated_sql},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            {"error": f"SQL execution error: {e}", "generated_sql": generated_sql},
            ensure_ascii=False,
        )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
