"""Load a shop from CSV files, or write one out as CSV templates.

    python -m margin_guard.importer export DIR [--db PATH]     # the demo shop as CSVs (templates)
    python -m margin_guard.importer import DIR --db NEW.db     # validate, then load into a new database
    python -m margin_guard.importer check DIR                  # validate only, write nothing

One file per table, UTF-8, header row first. Dates are YYYY-MM-DD; costs are
USD per lb; margins are fractions (0.25 = 25%). Aliases are separated by "|".

Validation is all-or-nothing: every row of every file is checked (types,
ranges, references between files, duplicates) and if anything is wrong,
nothing is written and every problem is listed with its file, row and column.
A partial load would produce margins that look right and aren't.

quote_lines.csv may leave material_cost_basis or conversion_cost blank: the
basis is then computed from the BOM and price history at the quote date, and
conversion cost from parts.csv, the same way the pricing system would.
"""

import argparse
import csv
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from . import db, impact, money
from .money import D, out


class ImportFailed(Exception):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s); nothing was imported")
        self.problems = problems


# ------------------------------------------------------------------ column types
# Each parser takes the raw cell and returns the stored value or raises ValueError
# with a message a person can act on.


def text(v: str) -> str:
    if not v.strip():
        raise ValueError("is empty")
    return v.strip()


def optional_text(v: str) -> str | None:
    return v.strip() or None


def _decimal(v: str) -> Decimal:
    try:
        d = Decimal(v.strip().replace(",", "").lstrip("$"))
    except InvalidOperation:
        raise ValueError(f"{v!r} is not a number") from None
    if not d.is_finite():
        raise ValueError(f"{v!r} is not a number")
    return d


def cost(v: str) -> float:
    d = _decimal(v)
    if d <= 0:
        raise ValueError(f"{v} must be more than 0")
    return out(money.cost(d))


def price(v: str) -> float:
    d = _decimal(v)
    if d <= 0:
        raise ValueError(f"{v} must be more than 0")
    return out(money.price(d))


def nonneg_price(v: str) -> float:
    d = _decimal(v)
    if d < 0:
        raise ValueError(f"{v} can't be negative")
    return out(money.price(d))


def fraction(v: str) -> float:
    d = _decimal(v)
    if not 0 <= d < 1:
        raise ValueError(f"{v} must be a fraction from 0 to 1 (0.25 = 25%)")
    return float(d)


def positive_float(v: str) -> float:
    d = _decimal(v)
    if d <= 0:
        raise ValueError(f"{v} must be more than 0")
    return float(d)


def positive_int(v: str) -> int:
    d = _decimal(v)
    if d <= 0 or d != d.to_integral_value():
        raise ValueError(f"{v} must be a whole number above 0")
    return int(d)


def iso_date(v: str) -> str:
    try:
        return date.fromisoformat(v.strip()).isoformat()
    except ValueError:
        raise ValueError(f"{v!r} is not a date (YYYY-MM-DD)") from None


def optional_date(v: str) -> str | None:
    return iso_date(v) if v.strip() else None


def flag(v: str) -> int:
    s = v.strip().lower()
    if s in ("1", "true", "yes", "y"):
        return 1
    if s in ("", "0", "false", "no", "n"):
        return 0
    raise ValueError(f"{v!r} must be 1/0 or yes/no")


def one_of(*allowed: str) -> Callable[[str], str]:
    def parse(v: str) -> str:
        s = v.strip().lower()
        if s not in allowed:
            raise ValueError(f"{v!r} must be one of {', '.join(allowed)}")
        return s
    return parse


def aliases(v: str) -> str:
    import json
    return json.dumps([a.strip() for a in v.split("|") if a.strip()])


# ------------------------------------------------------------------ files


@dataclass
class Table:
    file: str
    table: str
    columns: dict[str, Callable[[str], object]]
    required: tuple[str, ...]                     # header columns that must be present
    key: tuple[str, ...] = ()                     # unique per file
    refs: dict[str, str] = field(default_factory=dict)   # column -> file whose key it must match


TABLES = [
    Table("vendors.csv", "vendors", {"id": text, "name": text, "email_domain": lambda v: text(v).lower()},
          ("id", "name", "email_domain"), key=("id",)),
    Table("materials.csv", "materials",
          {"id": text, "name": text, "category": text, "cost_per_lb": cost, "aliases": aliases},
          ("id", "name", "category", "cost_per_lb"), key=("id",)),
    Table("material_vendors.csv", "material_vendors",
          {"material_id": text, "vendor_id": text, "is_costing": flag},
          ("material_id", "vendor_id", "is_costing"), key=("material_id", "vendor_id"),
          refs={"material_id": "materials.csv", "vendor_id": "vendors.csv"}),
    Table("price_history.csv", "material_price_history",
          {"material_id": text, "vendor_id": optional_text, "cost_per_lb": cost, "effective_date": iso_date},
          ("material_id", "cost_per_lb", "effective_date"),
          refs={"material_id": "materials.csv", "vendor_id": "vendors.csv"}),
    Table("parts.csv", "parts", {"id": text, "name": text, "conversion_cost": nonneg_price},
          ("id", "name", "conversion_cost"), key=("id",)),
    Table("bom.csv", "part_materials",
          {"part_id": text, "material_id": text, "lb_per_unit": positive_float, "scrap_rate": fraction},
          ("part_id", "material_id", "lb_per_unit"), key=("part_id", "material_id"),
          refs={"part_id": "parts.csv", "material_id": "materials.csv"}),
    Table("customers.csv", "customers",
          {"id": text, "name": text, "tier": one_of("key", "standard"), "price_lock_until": optional_date,
           "contract_note": optional_text, "buyer_name": optional_text, "buyer_phone": optional_text,
           "buyer_email": optional_text, "account_manager": optional_text, "account_manager_phone": optional_text},
          ("id", "name"), key=("id",)),
    Table("quotes.csv", "quotes",
          {"id": text, "customer_id": text, "status": one_of("open", "won", "lost", "expired"),
           "issued_date": iso_date, "valid_until": iso_date, "margin_floor": fraction, "ordered_date": optional_date},
          ("id", "customer_id", "status", "issued_date", "valid_until", "margin_floor"), key=("id",),
          refs={"customer_id": "customers.csv"}),
    Table("quote_lines.csv", "quote_lines",
          {"quote_id": text, "part_id": text, "qty": positive_int, "unit_price": price,
           "material_cost_basis": lambda v: nonneg_price(v) if v.strip() else None,
           "conversion_cost": lambda v: nonneg_price(v) if v.strip() else None},
          ("quote_id", "part_id", "qty", "unit_price"),
          refs={"quote_id": "quotes.csv", "part_id": "parts.csv"}),
]
DEFAULTS = {"tier": "standard", "scrap_rate": 0.0, "aliases": "[]", "is_costing": 0}


def _read(folder: Path, t: Table, problems: list[str]) -> list[dict]:
    path = folder / t.file
    if not path.exists():
        problems.append(f"{t.file}: file missing")
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in t.required if c not in header]
        if missing:
            problems.append(f"{t.file}: missing column(s) {', '.join(missing)}")
            return []
        unknown = [h for h in header if h and h not in t.columns]
        if unknown:
            problems.append(f"{t.file}: unknown column(s) {', '.join(unknown)}")
        rows = []
        for n, raw in enumerate(reader, start=2):        # row 1 is the header
            raw = {(k or "").strip(): (v or "") for k, v in raw.items()}
            if not any(v.strip() for v in raw.values()):
                continue                                 # blank line
            row, ok = {"_row": n}, True
            for col, parse in t.columns.items():
                if col not in raw:
                    row[col] = DEFAULTS.get(col)
                    continue
                try:
                    row[col] = parse(raw[col])
                except ValueError as exc:
                    problems.append(f"{t.file} row {n}, {col}: {exc}")
                    ok = False
            if ok:
                rows.append(row)
        return rows


def validate(folder: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """Parse and cross-check every file. Returns (rows by file, problems)."""
    problems: list[str] = []
    data = {t.file: _read(folder, t, problems) for t in TABLES}
    keys = {t.file: set() for t in TABLES}
    for t in TABLES:
        for r in data[t.file]:
            if t.key:
                k = tuple(r[c] for c in t.key)
                if k in keys[t.file]:
                    problems.append(f"{t.file} row {r['_row']}: duplicate {'/'.join(t.key)} {'/'.join(map(str, k))}")
                keys[t.file].add(k)
    ids = {f: {k[0] for k in ks} for f, ks in keys.items()}
    for t in TABLES:
        for r in data[t.file]:
            for col, target in t.refs.items():
                if r[col] is not None and r[col] not in ids[target]:
                    problems.append(f"{t.file} row {r['_row']}, {col}: {r[col]!r} is not in {target}")

    costing: dict[str, list] = {}
    for r in data["material_vendors.csv"]:
        if r["is_costing"]:
            costing.setdefault(r["material_id"], []).append(r["vendor_id"])
    for r in data["materials.csv"]:
        if r["id"] not in costing:
            problems.append(f"materials.csv row {r['_row']}: {r['id']} has no costing supplier; mark exactly one "
                            "in material_vendors.csv (is_costing = 1)")
    for m, vendors in costing.items():
        if len(vendors) > 1:
            problems.append(f"material_vendors.csv: {m} has {len(vendors)} costing suppliers ({', '.join(vendors)});"
                            " mark exactly one")
    supplied = {(r["material_id"], r["vendor_id"]) for r in data["material_vendors.csv"]}
    for r in data["price_history.csv"]:
        if r["vendor_id"] and (r["material_id"], r["vendor_id"]) not in supplied:
            problems.append(f"price_history.csv row {r['_row']}: {r['vendor_id']} isn't listed as a supplier of "
                            f"{r['material_id']} in material_vendors.csv")

    parts_with_bom = {r["part_id"] for r in data["bom.csv"]}
    for r in data["parts.csv"]:
        if r["id"] not in parts_with_bom:
            problems.append(f"parts.csv row {r['_row']}: part {r['id']} has no materials in bom.csv")
    first_history = {}
    for r in data["price_history.csv"]:
        m = r["material_id"]
        first_history[m] = min(first_history.get(m, r["effective_date"]), r["effective_date"])
    for r in data["quotes.csv"]:
        if r["valid_until"] < r["issued_date"]:
            problems.append(f"quotes.csv row {r['_row']}: valid_until is before issued_date")
        if r["status"] == "won" and not r["ordered_date"]:
            problems.append(f"quotes.csv row {r['_row']}: a won quote needs an ordered_date")
        if r["ordered_date"] and r["status"] != "won":
            problems.append(f"quotes.csv row {r['_row']}: ordered_date is only for won quotes")
        if r["ordered_date"] and r["ordered_date"] < r["issued_date"]:
            problems.append(f"quotes.csv row {r['_row']}: ordered_date is before issued_date")
    quotes_with_lines = {r["quote_id"] for r in data["quote_lines.csv"]}
    for r in data["quotes.csv"]:
        if r["id"] not in quotes_with_lines:
            problems.append(f"quotes.csv row {r['_row']}: quote {r['id']} has no lines in quote_lines.csv")
    issued = {r["id"]: r["issued_date"] for r in data["quotes.csv"]}
    bom_by_part: dict[str, list[str]] = {}
    for r in data["bom.csv"]:
        bom_by_part.setdefault(r["part_id"], []).append(r["material_id"])
    for r in data["quote_lines.csv"]:
        if r["material_cost_basis"] is not None:
            continue
        when = issued.get(r["quote_id"])
        for m in bom_by_part.get(r["part_id"], []):
            if when and (m not in first_history or first_history[m] > when):
                problems.append(f"quote_lines.csv row {r['_row']}: material_cost_basis is blank and {m} has no "
                                f"price history on or before the quote date {when}; give the basis or the history")
    return data, problems


def load(folder: Path, conn: sqlite3.Connection) -> dict[str, int]:
    """Validate `folder` and load it into an empty database. Raises ImportFailed."""
    data, problems = validate(folder)
    if problems:
        raise ImportFailed(problems)
    if conn.execute("SELECT name FROM sqlite_master WHERE name = 'quotes'").fetchone() and \
            conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]:
        raise ImportFailed(["the target database already has quotes; import into a new database"])
    db.init_schema(conn)
    try:
        for t in TABLES:
            rows = data[t.file]
            if t.file == "quote_lines.csv":
                continue
            cols = [c for c in t.columns if c != "is_costing"]
            if t.file == "material_vendors.csv":
                cols = ["material_id", "vendor_id", "is_primary"]
                rows = [{**r, "is_primary": r["is_costing"]} for r in rows]
            conn.executemany(
                f"INSERT INTO {t.table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [tuple(r[c] for c in cols) for r in rows])
        # Quote lines last: a blank basis is computed from the history just loaded.
        conversion = {r["id"]: r["conversion_cost"] for r in data["parts.csv"]}
        issued = {r["id"]: r["issued_date"] for r in data["quotes.csv"]}
        for r in data["quote_lines.csv"]:
            basis = r["material_cost_basis"]
            if basis is None:
                basis = out(money.price(sum(
                    (D(m["lb_per_unit"]) * (1 + D(m["scrap_rate"]))
                     * D(impact.cost_on(conn, m["material_id"], issued[r["quote_id"]]))
                     for m in conn.execute("SELECT * FROM part_materials WHERE part_id = ?", (r["part_id"],))),
                    money.ZERO)))
            conv = r["conversion_cost"] if r["conversion_cost"] is not None else conversion[r["part_id"]]
            conn.execute(
                "INSERT INTO quote_lines (quote_id, part_id, qty, unit_price, material_cost_basis, conversion_cost)"
                " VALUES (?, ?, ?, ?, ?, ?)", (r["quote_id"], r["part_id"], r["qty"], r["unit_price"], basis, conv))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {t.file: len(data[t.file]) for t in TABLES}


# ------------------------------------------------------------------ export


EXPORTS = {
    "vendors.csv": "SELECT id, name, email_domain FROM vendors ORDER BY id",
    "materials.csv": "SELECT id, name, category, cost_per_lb, aliases FROM materials ORDER BY id",
    "material_vendors.csv": ("SELECT material_id, vendor_id, is_primary AS is_costing FROM material_vendors"
                             " ORDER BY material_id, vendor_id"),
    "price_history.csv": ("SELECT material_id, COALESCE(vendor_id, '') AS vendor_id, cost_per_lb, effective_date"
                          " FROM material_price_history ORDER BY material_id, effective_date, id"),
    "parts.csv": "SELECT id, name, conversion_cost FROM parts ORDER BY id",
    "bom.csv": "SELECT part_id, material_id, lb_per_unit, scrap_rate FROM part_materials ORDER BY part_id, material_id",
    "customers.csv": ("SELECT id, name, tier, price_lock_until, contract_note, buyer_name, buyer_phone, buyer_email,"
                      " account_manager, account_manager_phone FROM customers ORDER BY id"),
    "quotes.csv": ("SELECT id, customer_id, status, issued_date, valid_until, margin_floor, ordered_date"
                   " FROM quotes ORDER BY id"),
    "quote_lines.csv": ("SELECT quote_id, part_id, qty, unit_price, material_cost_basis, conversion_cost"
                        " FROM quote_lines ORDER BY quote_id, id"),
}


def export(conn: sqlite3.Connection, folder: Path) -> dict[str, int]:
    import json
    folder.mkdir(parents=True, exist_ok=True)
    counts = {}
    for file, sql in EXPORTS.items():
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        with (folder / file).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in rows:
                vals = ["" if v is None else v for v in r]
                if file == "materials.csv":
                    vals[cols.index("aliases")] = "|".join(json.loads(r["aliases"]))
                w.writerow(vals)
        counts[file] = len(rows)
    return counts


def main() -> None:
    from .config import DB_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["export", "import", "check"])
    ap.add_argument("folder", type=Path)
    ap.add_argument("--db", type=Path, default=None, help=f"database (export default: {DB_PATH})")
    args = ap.parse_args()

    if args.command == "export":
        counts = export(db.connect(args.db or DB_PATH), args.folder)
        print(f"Wrote {sum(counts.values())} rows to {args.folder}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        return
    if args.command == "check":
        _, problems = validate(args.folder)
    else:
        if args.db is None:
            raise SystemExit("import needs --db NEW.db (a new database; the demo database is never overwritten)")
        if args.db.exists():
            raise SystemExit(f"{args.db} already exists; import into a new database")
        conn = db.connect(args.db)
        try:
            counts = load(args.folder, conn)
            print(f"Imported into {args.db}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
            return
        except ImportFailed as exc:
            conn.close()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{args.db}{suffix}").unlink(missing_ok=True)
            problems = exc.problems
    if problems:
        print(f"{len(problems)} problem(s); nothing was imported:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)
    print("All files are valid.")


if __name__ == "__main__":
    main()
