"""
Deploys the customer_orders Unity Catalog Metric View.

Works two ways:
  - As a local script: `python metric_views/deploy_metric_view.py`
    (reuses databricks_query.py's SQL connector to run remotely against the
    warehouse).
  - Pasted into and run as a Databricks notebook cell (e.g. via the
    Databricks web UI on serverless compute): uses the notebook's built-in
    `spark` session directly — no credentials needed. Notebook cells are
    executed via exec(), so `__file__` is never defined there.
"""
import pathlib

YAML_FILENAME = "customer_orders_metric_view.yml"
VIEW_FQN = "demo.diamond.vw_customer_orders_metrics"


def _find_yaml_path() -> pathlib.Path:
    try:
        candidate = pathlib.Path(__file__).resolve().parent / YAML_FILENAME
        if candidate.exists():
            return candidate
    except NameError:
        pass  # running as a pasted notebook cell — __file__ doesn't exist

    # Fall back to locating it relative to the current working directory,
    # covering both "cwd is metric_views/" and "cwd is the repo root".
    for candidate in (
        pathlib.Path.cwd() / YAML_FILENAME,
        pathlib.Path.cwd() / "metric_views" / YAML_FILENAME,
    ):
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not locate {YAML_FILENAME} — run this from the repo root or "
        f"the metric_views/ directory."
    )


def deploy() -> None:
    yaml_body = _find_yaml_path().read_text()
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

    if "spark" in globals():
        # Running inside a Databricks notebook — use the built-in session.
        spark.sql(ddl)
    else:
        # Running as a local script — connect out via the SQL connector.
        import os
        import sys

        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
        except NameError:
            sys.path.insert(0, str(pathlib.Path.cwd()))
        from databricks_query import _get_connection

        with _get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(ddl)

    print(f"Deployed metric view: {VIEW_FQN}")


if __name__ == "__main__":
    deploy()
