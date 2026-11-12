"""Invoice import from the console: upload, map columns, match, preview, commit, history.

An estimator shouldn't need Python to check an invoice export. This is the flow
behind the console's Imports view, built on the same code as the command line
(invoices.parse_rows / check_rows), so the screen and the CLI can't disagree:

    stage     the uploaded CSV is stored as-is; nothing else is written. Headers are
              read and each field gets a suggested column ("Doc No" -> invoice number)
    preview   with the chosen mapping: every supplier name matched to a supplier on
              file (or asked about), every row validated, every item matched to a
              material (or asked about), and the whole check run as a dry run inside
              a savepoint that is rolled back. The preview is exactly what a commit does.
    commit    the same steps for real, in one transaction: invoice lines, drift cards
              (or invoices merged into open ones), any item matches the person asked
              to remember (saved as catalog aliases), and the import's history record
    discard   the staged file is marked discarded; nothing was ever written

No model is involved anywhere in this flow.
"""

import csv
import io
import json
import re
import sqlite3
from datetime import datetime

from . import catalog, invoices
from .importer import ImportFailed

MAX_BYTES = 2_000_000
MAX_ROWS = 20_000

FIELDS = [
    {"key": "invoice_no", "label": "Invoice number", "required": True,
     "synonyms": ["invoice", "invoice no", "invoice number", "inv", "inv no", "doc no", "document", "document no"]},
    {"key": "line_no", "label": "Line", "required": True,
     "synonyms": ["line", "line no", "line number", "ln", "seq", "line item"]},
    {"key": "invoice_date", "label": "Invoice date", "required": True,
     "synonyms": ["invoice date", "date", "inv date", "doc date", "posting date", "document date"]},
    {"key": "supplier", "label": "Supplier", "required": True,
     "synonyms": ["vendor id", "supplier", "vendor", "supplier name", "vendor name", "supplier id"]},
    {"key": "item", "label": "Item as billed", "required": True,
     "synonyms": ["item", "description", "item description", "product", "material", "part"]},
    {"key": "qty", "label": "Quantity", "required": True,
     "synonyms": ["qty", "quantity", "qty billed", "quantity billed", "units"]},
    {"key": "unit", "label": "Unit", "required": True,
     "synonyms": ["unit", "uom", "unit of measure", "um", "u m"]},
    {"key": "unit_price", "label": "Unit price ($)", "required": True,
     "synonyms": ["unit price", "price", "price each", "unit cost", "rate", "price per unit"]},
    {"key": "pack_qty", "label": "Pack size (per-bag prices)", "required": False,
     "synonyms": ["pack qty", "pack size", "pack", "per pack"]},
]

UNITS = {
    "lb": "lb", "lbs": "lb", "pound": "lb", "pounds": "lb", "#": "lb",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilogram": "kg", "kilograms": "kg",
    "cwt": "cwt", "hundredweight": "cwt",
    "short_ton": "short_ton", "ton": "short_ton", "tons": "short_ton", "st": "short_ton", "short ton": "short_ton",
    "metric_ton": "metric_ton", "mt": "metric_ton", "t": "metric_ton", "tonne": "metric_ton", "metric ton": "metric_ton",
}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y")


class ImportError_(ValueError):
    pass


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Each field's most likely column: an exact name or synonym first, then containment."""
    normalized = {h: _norm(h) for h in headers}
    taken: set[str] = set()
    out: dict[str, str | None] = {}
    for f in FIELDS:
        names = [_norm(f["key"]), *(_norm(s) for s in f["synonyms"])]
        pick = next((h for h, n in normalized.items() if n in names and h not in taken), None)
        if pick is None:
            pick = next((h for h, n in normalized.items() if h not in taken and any(s and s in n for s in names[1:])),
                        None)
        if pick:
            taken.add(pick)
        out[f["key"]] = pick
    return out


def match_supplier(conn: sqlite3.Connection, text: str) -> str | None:
    """A supplier on file from what the export calls it: id, name, email domain, or a
    name either side contains ("Midwest Polymer" -> Midwest Polymer Supply)."""
    t = _norm(text)
    if not t:
        return None
    vendors = conn.execute("SELECT id, name, email_domain FROM vendors").fetchall()
    for v in vendors:
        if t in (_norm(v["id"]), _norm(v["name"]), _norm(v["email_domain"]), _norm(v["email_domain"].split(".")[0])):
            return v["id"]
    hits = [v["id"] for v in vendors if t in _norm(v["name"]) or _norm(v["name"]) in t]
    return hits[0] if len(hits) == 1 else None


def _date(text: str) -> str:
    s = (text or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s            # left as written; the validator reports it


# ------------------------------------------------------------------ stage


def stage(conn: sqlite3.Connection, filename: str, text: str) -> dict:
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ImportError_(f"the file is over {MAX_BYTES // 1_000_000} MB; split it and import the parts")
    rows = [r for r in csv.reader(io.StringIO(text.lstrip("﻿"))) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ImportError_("the file needs a header row and at least one invoice line")
    if len(rows) - 1 > MAX_ROWS:
        raise ImportError_(f"the file has {len(rows) - 1:,} lines; the limit is {MAX_ROWS:,} per import")
    headers = [h.strip() for h in rows[0]]
    if len(set(headers)) != len(headers) or not all(headers):
        raise ImportError_("every column needs a distinct, non-empty header")
    cur = conn.execute(
        "INSERT INTO imports (kind, filename, status, csv_text, headers, row_count) VALUES ('invoices', ?, 'staged', ?, ?, ?)",
        (filename, text, json.dumps(headers), len(rows) - 1))
    conn.commit()
    return {"import_id": cur.lastrowid, "filename": filename, "headers": headers, "row_count": len(rows) - 1,
            "sample": rows[1:6], "mapping": suggest_mapping(headers), "fields": FIELDS}


def _staged(conn: sqlite3.Connection, import_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
    if row is None:
        raise ImportError_(f"import {import_id} not found")
    if row["status"] != "staged":
        raise ImportError_(f"import {import_id} is already {row['status']}")
    return row


# ------------------------------------------------------------------ preview / commit


def _plan(conn: sqlite3.Connection, imp: sqlite3.Row, mapping: dict, suppliers: dict, matches: dict) -> dict:
    """Everything short of writing: mapping check, supplier matching, validation, item matching."""
    headers = json.loads(imp["headers"])
    missing = [f["label"] for f in FIELDS if f["required"] and not mapping.get(f["key"])]
    bad = [c for c in mapping.values() if c and c not in headers]
    if missing or bad:
        return {"stage": "mapping", "problems": [f"choose a column for: {', '.join(missing)}"] * bool(missing)
                + [f"no column named {c!r} in the file" for c in bad]}

    reader = csv.DictReader(io.StringIO(imp["csv_text"].lstrip("﻿")))
    raw_rows = [(n, {(k or "").strip(): (v or "") for k, v in r.items()}) for n, r in enumerate(reader, start=2)]

    # Suppliers: every distinct name in the file must resolve to a supplier on file.
    names = sorted({r[mapping["supplier"]].strip() for _, r in raw_rows if r.get(mapping["supplier"], "").strip()})
    supplier_rows = []
    for name in names:
        auto = match_supplier(conn, name)
        chosen = suppliers.get(name) or auto
        supplier_rows.append({"text": name, "auto": auto, "vendor_id": chosen})
    unmatched = [s["text"] for s in supplier_rows if not s["vendor_id"]]

    canonical = []
    for n, r in raw_rows:
        row = {f["key"]: r.get(mapping[f["key"]], "") if mapping.get(f["key"]) else "" for f in FIELDS}
        supplier_text = row.pop("supplier").strip()
        row["vendor_id"] = next((s["vendor_id"] for s in supplier_rows if s["text"] == supplier_text), None) or ""
        row["unit"] = UNITS.get(row["unit"].strip().lower(), row["unit"].strip().lower())
        row["invoice_date"] = _date(row["invoice_date"])
        canonical.append((n, row))

    plan = {"suppliers": supplier_rows, "items": [], "problems": []}
    if unmatched:
        plan.update(stage="suppliers", problems=[f"match the supplier '{t}' to one on file" for t in unmatched])
        return plan
    try:
        rows = invoices.parse_rows(conn, canonical)
    except ImportFailed as exc:
        plan.update(stage="errors", problems=exc.problems)
        return plan

    # Items: matched automatically, by a person on this screen, or left unmatched (reported, not guessed).
    supplied = {}
    for v in {r["vendor_id"] for r in rows}:
        supplied[v] = [{"id": m["id"], "name": m["name"]} for m in conn.execute(
            """SELECT m.id, m.name FROM material_vendors mv JOIN materials m ON m.id = mv.material_id
               WHERE mv.vendor_id = ? ORDER BY m.name""", (v,))]
    overrides: dict[tuple[str, str], str] = {}
    for key in sorted({(r["vendor_id"], r["item"]) for r in rows}):
        vendor, item = key
        auto = catalog.resolve_material(conn, item, vendor)
        chosen = matches.get(f"{vendor}|{item}")
        if chosen is not None:
            overrides[(vendor, item.strip().lower())] = chosen
        plan["items"].append({"key": f"{vendor}|{item}", "vendor_id": vendor, "item": item,
                              "auto": auto.material_id, "method": auto.method, "candidates": auto.candidates,
                              "chosen": chosen, "options": supplied.get(vendor, [])})
    plan.update(stage="ready", rows=rows, overrides=overrides)
    return plan


def _summary(report: dict) -> dict:
    return {k: report[k] for k in ("lines", "at_price", "above", "below", "already_on_file", "overpaid_usd")} | {
        "not_judged": len(report["not_judged"]),
        "drifts": report["drifts"],
        "cards_new": sum(1 for d in report["drifts"] if d["status"] in ("new", "new_after_decision")),
        "cards_merged": sum(1 for d in report["drifts"] if d["status"] == "merged"),
    }


def preview(conn: sqlite3.Connection, import_id: int, mapping: dict, suppliers: dict | None = None,
            matches: dict | None = None) -> dict:
    imp = _staged(conn, import_id)
    plan = _plan(conn, imp, mapping, suppliers or {}, matches or {})
    out = {k: plan.get(k) for k in ("stage", "problems", "suppliers", "items")}
    if plan["stage"] != "ready":
        return out
    conn.commit()                            # start the dry run from a clean slate
    conn.execute("SAVEPOINT import_preview")
    try:
        report = invoices.check_rows(conn, plan["rows"], source=imp["filename"], overrides=plan["overrides"],
                                     commit=False)
    finally:
        conn.execute("ROLLBACK TO import_preview")
        conn.execute("RELEASE import_preview")
    return out | {"summary": _summary(report), "lines": report["line_results"], "not_judged": report["not_judged"]}


def commit(conn: sqlite3.Connection, import_id: int, mapping: dict, suppliers: dict | None = None,
           matches: dict | None = None, remember: bool = False) -> dict:
    """Write the import in one transaction. Raises ImportError_ unless the preview was ready."""
    imp = _staged(conn, import_id)
    plan = _plan(conn, imp, mapping, suppliers or {}, matches or {})
    if plan["stage"] != "ready":
        raise ImportError_("; ".join(plan["problems"]) or "the import isn't ready")
    try:
        report = invoices.check_rows(conn, plan["rows"], source=imp["filename"], overrides=plan["overrides"],
                                     commit=False)
        remembered = _remember(conn, plan["overrides"]) if remember else []
        summary = _summary(report) | {"remembered": remembered}
        conn.execute(
            """UPDATE imports SET status = 'committed', mapping = ?, summary = ?, committed_at = datetime('now')
               WHERE id = ?""",
            (json.dumps({"columns": mapping, "suppliers": suppliers or {}, "matches": matches or {}}),
             json.dumps(summary), import_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"summary": summary, "lines": report["line_results"], "not_judged": report["not_judged"]}


def _remember(conn: sqlite3.Connection, overrides: dict[tuple[str, str], str]) -> list[str]:
    """Save each item a person matched as an alias of its material, so it matches by itself next time."""
    saved = []
    for (vendor, item), material_id in overrides.items():
        if not material_id:
            continue
        row = conn.execute("SELECT aliases FROM materials WHERE id = ?", (material_id,)).fetchone()
        aliases = json.loads(row["aliases"])
        if catalog.normalize_name(item) not in {catalog.normalize_name(a) for a in aliases}:
            aliases.append(item)
            conn.execute("UPDATE materials SET aliases = ? WHERE id = ?", (json.dumps(aliases), material_id))
            saved.append(f"'{item}' -> {material_id}")
    return saved


def discard(conn: sqlite3.Connection, import_id: int) -> None:
    _staged(conn, import_id)
    conn.execute("UPDATE imports SET status = 'discarded' WHERE id = ?", (import_id,))
    conn.commit()


def history(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    out = []
    for r in conn.execute("SELECT id, kind, filename, status, row_count, summary, created_at, committed_at FROM imports"
                          " ORDER BY id DESC LIMIT ?", (limit,)):
        d = dict(r)
        d["summary"] = json.loads(d["summary"]) if d["summary"] else None
        out.append(d)
    return out
