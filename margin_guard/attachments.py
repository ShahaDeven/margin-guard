"""Supplier attachments (price sheets, price letters) as plain text for extraction.

Many real price changes arrive as an Excel price list or a PDF letter rather than
in the email body. Code turns each attachment into text deterministically:

    .xlsx / .xlsm   every non-empty row of every sheet, cells joined with " | "
    .csv            as written
    .pdf            the PDF's text layer, page by page

Claude then reads the email body plus these texts with the same extraction schema,
so unit conversion, catalog matching and the sanity checks stay in code. A PDF
with no text layer (a scan) is not guessed at: it is flagged, and the email goes
to a person.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePath

MAX_ROWS = 400            # a price list longer than this is cut, and says so
MAX_CHARS = 30_000        # per attachment, to keep one email inside one model call
MIN_PDF_TEXT = 20         # fewer characters than this means "no text layer"

CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".csv": "text/csv",
    ".pdf": "application/pdf",
}


@dataclass
class Rendered:
    text: str              # what the model reads ("" when nothing could be read)
    note: str | None       # why something was cut or could not be read


def content_type(filename: str) -> str:
    return CONTENT_TYPES.get(PurePath(filename).suffix.lower(), "application/octet-stream")


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.date().isoformat() if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, float):
        return repr(v).removesuffix(".0") if v.is_integer() else repr(v)
    return str(v).strip()


def _sheet_rows(rows) -> tuple[list[str], bool]:
    out, cut = [], False
    for row in rows:
        cells = [_cell(v) for v in row]
        while cells and not cells[-1]:
            cells.pop()
        if not any(cells):
            continue
        if len(out) >= MAX_ROWS:
            cut = True
            break
        out.append(" | ".join(cells))
    return out, cut


def _xlsx(data: bytes) -> Rendered:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts, cut_any = [], False
    for ws in wb.worksheets:
        rows, cut = _sheet_rows(ws.iter_rows(values_only=True))
        cut_any |= cut
        if rows:
            parts.append(f"[sheet: {ws.title}]\n" + "\n".join(rows))
    wb.close()
    note = f"price list cut at {MAX_ROWS} rows per sheet" if cut_any else None
    return Rendered("\n\n".join(parts), note)


def _csv(data: bytes) -> Rendered:
    text = data.decode("utf-8-sig", errors="replace")
    rows, cut = _sheet_rows(csv.reader(io.StringIO(text)))
    return Rendered("\n".join(rows), f"price list cut at {MAX_ROWS} rows" if cut else None)


def _pdf(data: bytes) -> Rendered:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text() or "").strip() for p in reader.pages]
    text = "\n\n".join(f"[page {i}]\n{t}" for i, t in enumerate(pages, start=1) if t)
    if sum(len(t) for t in pages) < MIN_PDF_TEXT:
        return Rendered("", "PDF has no text layer (looks scanned); it needs a person to read it")
    return Rendered(text, None)


def render(filename: str, data: bytes) -> Rendered:
    """An attachment as text, or an empty text with the reason it couldn't be read."""
    suffix = PurePath(filename).suffix.lower()
    try:
        if suffix in (".xlsx", ".xlsm"):
            r = _xlsx(data)
        elif suffix == ".csv":
            r = _csv(data)
        elif suffix == ".pdf":
            r = _pdf(data)
        else:
            return Rendered("", f"{suffix or 'this'} attachments are not read")
    except Exception as exc:  # a corrupt file must not stop the inbox
        return Rendered("", f"could not read the file ({type(exc).__name__})")
    if len(r.text) > MAX_CHARS:
        r = Rendered(r.text[:MAX_CHARS], (r.note + "; " if r.note else "") + f"cut at {MAX_CHARS:,} characters")
    return r


def for_prompt(items: list[tuple[str, Rendered]]) -> str:
    """The attachments section of the extraction prompt."""
    blocks = []
    for filename, r in items:
        head = f"--- Attachment: {filename} ---"
        if not r.text:
            blocks.append(f"{head}\n[could not be read: {r.note}]")
        else:
            blocks.append(f"{head}\n{r.text}" + (f"\n[note: {r.note}]" if r.note else ""))
    return "\n\n".join(blocks)


def add(conn, email_id: str, filename: str, data: bytes) -> int:
    """Store an attachment with its rendered text. Returns its id."""
    r = render(filename, data)
    cur = conn.execute(
        "INSERT INTO email_attachments (email_id, filename, content_type, data, text, note) VALUES (?, ?, ?, ?, ?, ?)",
        (email_id, filename, content_type(filename), data, r.text, r.note),
    )
    return cur.lastrowid


def load(conn, email_id: str) -> list[tuple[str, Rendered]]:
    rows = conn.execute(
        "SELECT filename, text, note FROM email_attachments WHERE email_id = ? ORDER BY id", (email_id,)
    ).fetchall()
    return [(r["filename"], Rendered(r["text"] or "", r["note"])) for r in rows]
