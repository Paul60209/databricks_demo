"""
Databricks Query Functions
==========================
Two semantic query functions over the diamond layer (demo.diamond.*).
Designed to be registered as MCP server tools for AI agent consumption.

Dependencies:
    pip install databricks-sql-connector pandas

Connection config:
    Set the following environment variables before use:
        DATABRICKS_HOST        e.g. adb-1234567890.12.azuredatabricks.net
        DATABRICKS_HTTP_PATH   e.g. /sql/1.0/warehouses/abcdef1234567890
        DATABRICKS_TOKEN       Personal Access Token or Service Principal token
"""

import os
import pandas as pd
from typing import Optional
from databricks import sql


# ── Connection helper ──────────────────────────────────────────────────────────

def _get_connection():
    """Return a Databricks SQL connection using environment variables."""
    host       = os.environ["DATABRICKS_HOST"]
    http_path  = os.environ["DATABRICKS_HTTP_PATH"]
    token      = os.environ["DATABRICKS_TOKEN"]
    return sql.connect(
        server_hostname=host,
        http_path=http_path,
        access_token=token,
    )


def _run_query(query: str, params: list = None) -> pd.DataFrame:
    """Execute a parameterized SQL query and return results as a DataFrame."""
    with _get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or [])
            columns = [desc[0] for desc in cursor.description]
            rows    = cursor.fetchall()
    return pd.DataFrame(rows, columns=columns)


# ── Query Function 1 ───────────────────────────────────────────────────────────

def get_customer_transaction_summary(
    customer_ids:   Optional[list[str]] = None,
    customer_names: Optional[list[str]] = None,
    months:         Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Query per-customer transaction count and total revenue.

    Args:
        customer_ids:   List of customer IDs to filter on (e.g. ["C001", "C002"]).
                        If None, all customers are included.
        customer_names: List of customer names to filter on (e.g. ["John Doe"]).
                        If None, all customers are included.
                        Combined with customer_ids using OR logic.
        months:         List of months to filter on in "YYYY-MM" format
                        (e.g. ["2025-01", "2025-02"]).
                        If None, all months are summed.

    Returns:
        pd.DataFrame with columns:
            customer_id, customer_name, country,
            order_month (or "ALL" when no month filter),
            total_order_count, total_order_amount, avg_order_value
    """
    # ── Build WHERE clauses ──────────────────────────────────────────
    filters = []
    params  = []

    # Customer filter (id OR name)
    customer_clauses = []
    if customer_ids:
        placeholders = ", ".join(["?"] * len(customer_ids))
        customer_clauses.append(f"customer_id IN ({placeholders})")
        params.extend(customer_ids)
    if customer_names:
        placeholders = ", ".join(["?"] * len(customer_names))
        customer_clauses.append(f"customer_name IN ({placeholders})")
        params.extend(customer_names)
    if customer_clauses:
        filters.append(f"({' OR '.join(customer_clauses)})")

    # Month filter  — convert "YYYY-MM" → date_trunc match
    if months:
        placeholders = ", ".join(["?"] * len(months))
        filters.append(
            f"DATE_FORMAT(order_month, 'yyyy-MM') IN ({placeholders})"
        )
        params.extend(months)

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

    # ── Select: keep month granularity when filter provided, else collapse ──
    if months:
        select_month = "DATE_FORMAT(order_month, 'yyyy-MM') AS order_month"
        group_month  = ", DATE_FORMAT(order_month, 'yyyy-MM')"
    else:
        select_month = "'ALL' AS order_month"
        group_month  = ""

    query = f"""
        SELECT
            customer_id,
            customer_name,
            country,
            {select_month},
            SUM(total_order_count)                                      AS total_order_count,
            ROUND(SUM(total_order_amount), 2)                           AS total_order_amount,
            ROUND(SUM(total_order_amount) / SUM(total_order_count), 2)  AS avg_order_value
        FROM demo.diamond.sem_customer_transaction_summary
        {where_sql}
        GROUP BY customer_id, customer_name, country{group_month}
        ORDER BY total_order_amount DESC
    """

    return _run_query(query, params)


# ── Query Function 2 ───────────────────────────────────────────────────────────

def get_regional_monthly_aov(
    countries: Optional[list[str]] = None,
    months:    Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Query AOV (Average Order Value) by region and month.

    Args:
        countries: List of country names to filter on
                   (e.g. ["Taiwan", "Japan"]).
                   If None, all regions are included.
        months:    List of months to filter on in "YYYY-MM" format
                   (e.g. ["2025-03", "2025-04"]).
                   If None, all months are included.

    Returns:
        pd.DataFrame with columns:
            country, order_month,
            total_order_count, total_order_amount, aov
    """
    # ── Build WHERE clauses ──────────────────────────────────────────
    filters = []
    params  = []

    if countries:
        placeholders = ", ".join(["?"] * len(countries))
        filters.append(f"country IN ({placeholders})")
        params.extend(countries)

    if months:
        placeholders = ", ".join(["?"] * len(months))
        filters.append(
            f"DATE_FORMAT(order_month, 'yyyy-MM') IN ({placeholders})"
        )
        params.extend(months)

    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""

    query = f"""
        SELECT
            country,
            DATE_FORMAT(order_month, 'yyyy-MM') AS order_month,
            SUM(total_order_count)                                      AS total_order_count,
            ROUND(SUM(total_order_amount), 2)                           AS total_order_amount,
            ROUND(SUM(total_order_amount) / SUM(total_order_count), 2)  AS aov
        FROM demo.diamond.sem_regional_monthly_aov
        {where_sql}
        GROUP BY country, DATE_FORMAT(order_month, 'yyyy-MM')
        ORDER BY country, order_month
    """

    return _run_query(query, params)


# ── Quick smoke test ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== Test 1: All customers, all months ===")
    df1 = get_customer_transaction_summary()
    print(df1.to_string(index=False))

    print("\n=== Test 2: C001 + C005, Jan-Feb 2025 ===")
    df2 = get_customer_transaction_summary(
        customer_ids=["C001", "C005"],
        months=["2025-01", "2025-02"]
    )
    print(df2.to_string(index=False))

    print("\n=== Test 3: All regions, all months ===")
    df3 = get_regional_monthly_aov()
    print(df3.to_string(index=False))

    print("\n=== Test 4: Taiwan + Japan, Q1 2025 ===")
    df4 = get_regional_monthly_aov(
        countries=["Taiwan", "Japan"],
        months=["2025-01", "2025-02", "2025-03"]
    )
    print(df4.to_string(index=False))
