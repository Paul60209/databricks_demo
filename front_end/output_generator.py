"""
Generate downloadable output files from agent tool_results.
All functions return bytes suitable for Chainlit file attachments.
"""

import ast
import io
import json
from datetime import datetime

import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> list | dict | None:
    """
    tool_results[i]['result'] is str(mcp_response), which looks like:
      "[{'type': 'text', 'text': '[{...actual JSON...}]', 'id': '...'}]"
    Parse the outer Python repr, then extract the 'text' field containing real JSON.
    """
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict) and "text" in parsed[0]:
            return json.loads(parsed[0]["text"])
        return parsed
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return None


def _results_to_df(tool_results: list[dict]) -> pd.DataFrame:
    """Flatten tool_results into a single DataFrame."""
    frames = []
    for item in tool_results:
        data = _extract_json(item.get("result", "[]"))
        if isinstance(data, list) and data:
            frames.append(pd.DataFrame(data))
        elif isinstance(data, dict) and "data" in data:
            frames.append(pd.DataFrame(data["data"]))
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ── CSV ───────────────────────────────────────────────────────────────────────

def to_csv(tool_results: list[dict]) -> bytes:
    df = _results_to_df(tool_results)
    if df.empty:
        return b"no data"
    return df.to_csv(index=False).encode("utf-8-sig")  # utf-8-sig for Excel compatibility


# ── Excel ─────────────────────────────────────────────────────────────────────

def to_excel(tool_results: list[dict]) -> bytes:
    df = _results_to_df(tool_results)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        if df.empty:
            pd.DataFrame({"info": ["no data"]}).to_excel(writer, index=False)
        else:
            df.to_excel(writer, index=False, sheet_name="Results")
    return buf.getvalue()


# ── PDF ───────────────────────────────────────────────────────────────────────

def to_pdf(question: str, answer: str, tool_results: list[dict]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Sony Business Intelligence Report", ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
    pdf.ln(4)

    # Question
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Question", ln=True)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, question)
    pdf.ln(3)

    # Answer
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Answer", ln=True)
    pdf.set_font("Helvetica", "", 10)
    # Strip markdown for plain PDF
    clean_answer = answer.replace("**", "").replace("*", "").replace("`", "")
    pdf.multi_cell(0, 6, clean_answer[:3000])
    pdf.ln(3)

    # Data table
    df = _results_to_df(tool_results)
    if not df.empty:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, "Data", ln=True)
        pdf.set_font("Helvetica", "B", 8)

        col_w = min(35, 180 // len(df.columns))
        for col in df.columns:
            pdf.cell(col_w, 7, str(col)[:15], border=1)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        for _, row in df.head(30).iterrows():
            for val in row:
                pdf.cell(col_w, 6, str(val)[:15], border=1)
            pdf.ln()

    return pdf.output()


# ── PNG chart ─────────────────────────────────────────────────────────────────

def to_png(tool_results: list[dict], question: str = "") -> bytes:
    df = _results_to_df(tool_results)
    fig, ax = plt.subplots(figsize=(10, 5))

    if df.empty:
        ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=14)
    elif "order_month" in df.columns:
        _plot_time_series(ax, df)
    else:
        _plot_bar(ax, df)

    title = question[:70] + ("…" if len(question) > 70 else "")
    ax.set_title(title, fontsize=11, pad=10)
    ax.grid(axis="y", alpha=0.3)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return buf.getvalue()


def _plot_time_series(ax, df: pd.DataFrame):
    df = df.copy()
    df["order_month"] = pd.to_datetime(df["order_month"], errors="coerce")
    df = df.sort_values("order_month")

    value_col = next(
        (c for c in ["aov", "avg_order_value", "total_order_amount"] if c in df.columns),
        df.select_dtypes("number").columns[0] if not df.select_dtypes("number").empty else None,
    )
    if value_col is None:
        ax.text(0.5, 0.5, "No numeric column", ha="center", va="center")
        return

    group_col = next((c for c in ["country", "customer_name"] if c in df.columns), None)
    if group_col:
        for label, grp in df.groupby(group_col):
            ax.plot(grp["order_month"], grp[value_col], marker="o", label=label)
        ax.legend(fontsize=8)
    else:
        ax.plot(df["order_month"], df[value_col], marker="o")

    ax.set_xlabel("Month")
    ax.set_ylabel(value_col.replace("_", " ").title())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y-%m"))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")


def _plot_bar(ax, df: pd.DataFrame):
    label_col = next(
        (c for c in ["country", "customer_name", "customer_id"] if c in df.columns),
        df.columns[0],
    )
    value_col = next(
        (c for c in ["aov", "avg_order_value", "total_order_amount", "total_order_count"] if c in df.columns),
        df.select_dtypes("number").columns[0] if not df.select_dtypes("number").empty else None,
    )
    if value_col is None:
        ax.text(0.5, 0.5, "No numeric column", ha="center", va="center")
        return

    df_plot = df[[label_col, value_col]].dropna().head(15)
    bars = ax.barh(df_plot[label_col].astype(str), df_plot[value_col])
    ax.bar_label(bars, fmt="%.0f", padding=3, fontsize=8)
    ax.set_xlabel(value_col.replace("_", " ").title())
    ax.invert_yaxis()
