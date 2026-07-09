"""
Deploys the customer_orders Unity Catalog Metric View.
Reuses the same connection pattern as databricks_query.py.

Usage:
    python metric_views/deploy_metric_view.py
"""
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from databricks_query import _get_connection

VIEW_FQN = "demo.diamond.vw_customer_orders_metrics"
YAML_PATH = pathlib.Path(__file__).parent / "customer_orders_metric_view.yml"


def deploy() -> None:
    yaml_body = YAML_PATH.read_text()
    # Note: the YAML body must start at column 0 — any leading indentation on
    # its first line (e.g. from an indented f-string template) breaks the
    # top-level key alignment and the metric view definition fails to parse.
    ddl = (
        f"CREATE OR REPLACE VIEW {VIEW_FQN}\n"
        "WITH METRICS LANGUAGE YAML AS\n"
        "$$\n"
        f"{yaml_body}\n"
        "$$"
    )
    with _get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(ddl)
    print(f"Deployed metric view: {VIEW_FQN}")


if __name__ == "__main__":
    deploy()
