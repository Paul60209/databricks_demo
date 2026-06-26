"""
Parse files uploaded via Chainlit and return their content as a text string
to be appended to the user's question as context for the agent.
"""

import io
import pandas as pd

_MAX_ROWS = 50
_MAX_TEXT_CHARS = 3000


async def process_files(elements: list) -> str:
    """
    Accepts a list of Chainlit element objects from message.elements.
    Returns a combined text block of file contents, or empty string if none.
    """
    if not elements:
        return ""

    parts = []
    for el in elements:
        # Chainlit file elements have a .path or .content attribute
        name = getattr(el, "name", "") or ""
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""

        try:
            raw: bytes = _read_element(el)
            if not raw:
                continue

            if ext == "csv":
                text = _parse_tabular(raw, name, sep=",")
            elif ext in ("xlsx", "xls"):
                text = _parse_excel(raw, name)
            elif ext == "pdf":
                text = _parse_pdf(raw, name)
            elif ext == "docx":
                text = _parse_docx(raw, name)
            else:
                continue  # unsupported — skip silently

            parts.append(text)
        except Exception as exc:
            parts.append(f"[Could not parse {name}: {exc}]")

    return "\n\n".join(parts)


def _read_element(el) -> bytes:
    """Read raw bytes from a Chainlit element (path-based or content-based)."""
    if hasattr(el, "content") and el.content:
        return el.content if isinstance(el.content, bytes) else el.content.encode()
    if hasattr(el, "path") and el.path:
        with open(el.path, "rb") as f:
            return f.read()
    return b""


def _parse_tabular(raw: bytes, name: str, sep: str = ",") -> str:
    df = pd.read_csv(io.BytesIO(raw), sep=sep)
    preview = df.head(_MAX_ROWS).to_markdown(index=False)
    return (
        f"### Uploaded file: {name}\n"
        f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\n"
        f"Columns: {', '.join(df.columns)}\n\n"
        f"{preview}"
    )


def _parse_excel(raw: bytes, name: str) -> str:
    df = pd.read_excel(io.BytesIO(raw))
    preview = df.head(_MAX_ROWS).to_markdown(index=False)
    return (
        f"### Uploaded file: {name}\n"
        f"Shape: {df.shape[0]} rows × {df.shape[1]} columns\n"
        f"Columns: {', '.join(df.columns)}\n\n"
        f"{preview}"
    )


def _parse_pdf(raw: bytes, name: str) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    full_text = "\n".join(text_parts)[:_MAX_TEXT_CHARS]
    return f"### Uploaded file: {name} (PDF)\n\n{full_text}"


def _parse_docx(raw: bytes, name: str) -> str:
    from docx import Document
    doc = Document(io.BytesIO(raw))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    full_text = "\n".join(paragraphs)[:_MAX_TEXT_CHARS]
    return f"### Uploaded file: {name} (Word)\n\n{full_text}"
