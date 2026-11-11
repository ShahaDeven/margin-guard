"""Invoice price drift: catch the increases nobody announced.

Suppliers don't always send a price notice. Sometimes the first sign of an
increase is the invoice. This checks every invoice line from an accounts-payable
export against the price on file for that supplier on the invoice date:

    at price       within 0.5% of what's on file
    above (drift)  billed more than on file: an unannounced increase, or an error
    below          billed less (reported, nothing to do)
    not judged     an item we don't stock, or no price on file for that supplier

Each drift (one per supplier + material + invoiced price) becomes a "needs a
look" card with the evidence: invoice, price on file and the history row it came
from, and dollars overpaid. A person applies it as a price change from the
invoice date (the normal impact and decision flow then runs on open quotes) or
dismisses it as a one-off. No model is involved: units, matching and the
comparison are all code.

    python -m margin_guard.invoices check data/invoices_demo.csv [--db PATH]

invoices.csv columns: invoice_no, line_no, invoice_date (YYYY-MM-DD), vendor_id,
item (the supplier's own item name), qty, unit (lb, kg, cwt, short_ton,
metric_ton), unit_price (USD per unit), pack_qty (optional, for per-bag prices).
Like the shop import, a file with any bad row loads nothing.
"""

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

from . import catalog, db, events, impact, money
from .importer import ImportFailed, iso_date, positive_float, price, text
from .leakage import history_row
from .money import D, out
from .parser import EventDraft
from .units import LB_PER_UNIT, to_cost_per_lb

DRIFT_TOLERANCE = D("0.005")     # within 0.5% of the price on file counts as billed at price

COLUMNS = {
    "invoice_no": text, "line_no": lambda v: int(positive_float(v)), "invoice_date": iso_date, "vendor_id": text,
    "item": text, "qty": positive_float, "unit": text, "unit_price": price,
    "pack_qty": lambda v: positive_float(v) if v.strip() else None,
}
REQUIRED = ("invoice_no", "line_no", "invoice_date", "vendor_id", "item", "qty", "unit", "unit_price")


def read(conn: sqlite3.Connection, path: Path) -> list[dict]:
    """Parse and validate an invoices CSV. Raises ImportFailed listing every problem."""
    problems: list[str] = []
    vendors = {r[0] for r in conn.execute("SELECT id FROM vendors")}
    rows: list[dict] = []
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise ImportFailed([f"{Path(path).name}: missing column(s) {', '.join(missing)}"])
        seen = set()
        for n, raw in enumerate(reader, start=2):
            raw = {(k or "").strip(): (v or "") for k, v in raw.items()}
            if not any(v.strip() for v in raw.values()):
                continue
            row, ok = {"_row": n}, True
            for col, parse in COLUMNS.items():
                try:
                    row[col] = parse(raw.get(col, "")) if col in raw or col in REQUIRED else None
                except ValueError as exc:
                    problems.append(f"row {n}, {col}: {exc}")
                    ok = False
            if not ok:
                continue
            row["unit"] = row["unit"].lower()
            if row["unit"] not in LB_PER_UNIT:
                problems.append(f"row {n}, unit: {row['unit']!r} must be one of {', '.join(LB_PER_UNIT)}")
            if row["vendor_id"] not in vendors:
                problems.append(f"row {n}, vendor_id: {row['vendor_id']!r} is not a supplier on file")
            key = (row["invoice_no"], row["line_no"])
            if key in seen:
                problems.append(f"row {n}: duplicate invoice line {key[0]}/{key[1]}")
            seen.add(key)
            rows.append(row)
    if problems:
        raise ImportFailed(problems)
    return rows


def check(conn: sqlite3.Connection, path: Path) -> dict:
    """Load an invoices CSV, judge every line, and raise a card per drift. Returns the report."""
    rows = read(conn, path)
    report = {"lines": len(rows), "at_price": 0, "above": 0, "below": 0, "not_judged": [], "drifts": [],
              "overpaid_usd": 0.0, "already_on_file": 0}
    overpaid = money.ZERO
    drifts: dict[tuple, dict] = {}

    for r in rows:
        cur = conn.execute(
            """INSERT OR IGNORE INTO invoice_lines
               (invoice_no, line_no, invoice_date, vendor_id, item, qty, unit, unit_price, pack_qty)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r["invoice_no"], r["line_no"], r["invoice_date"], r["vendor_id"], r["item"], r["qty"], r["unit"],
             r["unit_price"], r["pack_qty"]),
        )
        if not cur.rowcount:
            report["already_on_file"] += 1
            continue
        line_id = cur.lastrowid
        match = catalog.resolve_material(conn, r["item"], r["vendor_id"])
        if match.material_id is None:
            _mark(conn, line_id, "not_judged", None, None, None, f"item '{r['item']}' is {match.method}")
            why = (f"could be {' or '.join(match.candidates)}; can't tell which" if match.method == "ambiguous"
                   else "is not an item we stock from this supplier")
            report["not_judged"].append(f"{r['invoice_no']}/{r['line_no']}: '{r['item']}' {why}")
            continue
        m = match.material_id
        billed = to_cost_per_lb(r["unit_price"], r["unit"], r["pack_qty"])
        expected = impact.supplier_cost(conn, m, r["vendor_id"], r["invoice_date"])
        if expected is None:
            _mark(conn, line_id, "not_judged", m, billed, None, "no price on file for this supplier")
            report["not_judged"].append(f"{r['invoice_no']}/{r['line_no']}: no {r['vendor_id']} price on file for {m}")
            continue
        pct = money.pct((billed - D(expected)) / D(expected))
        status = "above" if pct > DRIFT_TOLERANCE else "below" if pct < -DRIFT_TOLERANCE else "at_price"
        _mark(conn, line_id, status, m, billed, expected, None)
        report[status] += 1
        if status != "above":
            continue

        pack = D(r["pack_qty"]) if r["pack_qty"] else D(1)
        lbs = D(r["qty"]) * pack * LB_PER_UNIT[r["unit"]]
        line_over = money.cents(D(r["qty"]) * D(r["unit_price"]) - lbs * D(expected))
        overpaid += line_over
        key = (r["vendor_id"], m, out(billed))
        d = drifts.setdefault(key, {
            "vendor_id": r["vendor_id"], "material_id": m, "item": r["item"], "billed": billed, "expected": expected,
            "pct": pct, "first_date": r["invoice_date"], "row": history_row(conn, m, r["invoice_date"]),
            "invoices": [], "overpaid": money.ZERO,
        })
        d["invoices"].append({"invoice_no": r["invoice_no"], "line_no": r["line_no"], "date": r["invoice_date"],
                              "overpaid_usd": out(line_over)})
        d["overpaid"] += line_over
        d["first_date"] = min(d["first_date"], r["invoice_date"])

    names = dict(conn.execute("SELECT id, name FROM vendors").fetchall())
    for d in drifts.values():
        row = d["row"]
        on_file = (f"${d['expected']:.4f}/lb is on file from {row['effective_date']}" if row
                   else f"${d['expected']:.4f}/lb is on file")
        invs = ", ".join(f"{i['invoice_no']} ({i['date']})" for i in d["invoices"])
        payload = {
            "kind": "invoice_drift",
            "email_id": None,
            "vendor_id": d["vendor_id"],
            "vendor_name": names.get(d["vendor_id"], d["vendor_id"]),
            "material_text": d["item"],
            "material_id": d["material_id"],
            "match_method": "invoice",
            "match_candidates": [d["material_id"]],
            "old_cost_per_lb": d["expected"],
            "new_cost_per_lb": out(d["billed"]),
            "pct_change": out(d["pct"]),
            "effective_date": d["first_date"],
            "invoices": d["invoices"],
            "overpaid_usd": out(money.cents(d["overpaid"])),
            "expected_row": row,
            "review_reasons": [
                f"{names.get(d['vendor_id'], d['vendor_id'])} billed {d['item']} at ${d['billed']:.4f}/lb on {invs}; "
                f"{on_file}, so that is {d['pct']:+.1%} with no price notice on file.",
                f"Overpaid on these lines: ${d['overpaid']:,.2f}.",
            ],
        }
        key = f"drift:{d['vendor_id']}:{d['material_id']}:{out(d['billed']):.4f}"
        event_id = events.append(conn, EventDraft("price_change.needs_review", key, payload), source_ref=f"invoices:{Path(path).name}")
        report["drifts"].append({k: payload[k] for k in ("vendor_name", "material_id", "material_text", "old_cost_per_lb",
                                                         "new_cost_per_lb", "pct_change", "effective_date", "overpaid_usd")}
                                | {"invoices": len(d["invoices"]), "new": event_id is not None})
    conn.commit()
    report["above"] = sum(len(d["invoices"]) for d in drifts.values())
    report["overpaid_usd"] = out(money.cents(overpaid))
    return report


def _mark(conn, line_id, status, material_id, billed, expected, note) -> None:
    conn.execute(
        """UPDATE invoice_lines SET status = ?, material_id = ?, billed_cost_per_lb = ?, expected_cost_per_lb = ?, note = ?
           WHERE id = ?""",
        (status, material_id, out(billed) if billed is not None else None, expected, note, line_id),
    )


def report_text(r: dict) -> str:
    lines = [
        f"{r['lines']} invoice lines: {r['at_price']} at price, {r['above']} above, {r['below']} below, "
        f"{len(r['not_judged'])} not judged" + (f", {r['already_on_file']} already checked" if r["already_on_file"] else ""),
        f"Overpaid on lines billed above the price on file: ${r['overpaid_usd']:,.2f}",
    ]
    for d in r["drifts"]:
        lines.append(f"  DRIFT  {d['vendor_name']}: {d['material_text']} ${d['old_cost_per_lb']:.4f} -> "
                     f"${d['new_cost_per_lb']:.4f}/lb ({d['pct_change']:+.1%}) from {d['effective_date']}, "
                     f"{d['invoices']} invoice(s), ${d['overpaid_usd']:,.2f} overpaid"
                     + ("" if d["new"] else "  [card already raised]"))
    lines += [f"  not judged: {n}" for n in r["not_judged"]]
    return "\n".join(lines)


def main() -> None:
    from .config import DB_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("csv", type=Path)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()
    conn = db.connect(args.db)
    db.init_schema(conn)
    try:
        r = check(conn, args.csv)
    except ImportFailed as exc:
        print(f"{len(exc.problems)} problem(s); nothing was loaded:", file=sys.stderr)
        for p in exc.problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)
    print(report_text(r))
    if r["drifts"]:
        print("\nRun the coordinator (or the console's agents) to put the drift cards in front of a person.")


if __name__ == "__main__":
    main()
