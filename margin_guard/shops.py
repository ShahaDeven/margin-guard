"""Shops the console can run on: the synthetic sample shop, and any shop loaded from the
nine CSV files (importer.py) through the console.

A loaded shop gets its own database in data/shops/; the sample shop is never written
over. The console works on one shop at a time and can switch between them.

    files     the person's CSVs are matched to the nine slots by name ("Suppliers.csv"
              fills vendors.csv), and any slot can be pointed at another file by hand
    check     importer.validate on a scratch copy: every problem with its file, row and
              column; nothing is written
    load      validate again, then load into a new database, all or nothing
"""

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import importer
from .config import ROOT

SHOPS_DIR = Path(os.getenv("MG_SHOPS_DIR", ROOT / "data" / "shops"))
REGISTRY = SHOPS_DIR / "shops.json"
SAMPLE_FILES = ROOT / "data" / "shop_csv"
SAMPLE_ID = "sample"

# The nine files, in the order a person would fill them, with what each one holds and the
# other names a file of that kind tends to have.
SLOTS = [
    ("vendors.csv", "Suppliers", "id, name, email domain (how a supplier's email is recognised)",
     ("vendors", "suppliers", "supplier")),
    ("materials.csv", "Materials", "id, name, category, cost per lb, other names a supplier uses",
     ("materials", "material", "compounds", "raw_materials")),
    ("material_vendors.csv", "Who supplies what", "material, supplier, and which supplier sets the cost",
     ("material_vendors", "material_suppliers", "supplier_materials", "sources")),
    ("price_history.csv", "Price history", "each material's cost per lb from a date, by supplier",
     ("price_history", "prices", "material_prices", "cost_history")),
    ("parts.csv", "Parts", "id, name, conversion cost per unit",
     ("parts", "part", "items", "products")),
    ("bom.csv", "Bills of materials", "pounds of each material per part, and scrap",
     ("bom", "boms", "bill_of_materials", "bills_of_materials", "part_materials")),
    ("customers.csv", "Customers", "tier, price lock, contract note, buyer and account manager",
     ("customers", "customer", "accounts")),
    ("quotes.csv", "Quotes", "status, dates, margin floor; won quotes with the order date",
     ("quotes", "quote", "quotations")),
    ("quote_lines.csv", "Quote lines", "part, quantity and unit price on each quote",
     ("quote_lines", "quotelines", "lines", "quote_items")),
]
SLOT_FILES = [s[0] for s in SLOTS]


def _norm(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_")


def match(names: list[str]) -> dict[str, str | None]:
    """Each slot's file among `names`, by name; None where none fits."""
    taken: set[str] = set()
    out: dict[str, str | None] = {}
    for file, _, _, alts in SLOTS:
        hit = next((n for n in names if n not in taken and _norm(n) in alts), None)
        out[file] = hit
        if hit:
            taken.add(hit)
    return out


_PROBLEM = re.compile(r"^(?P<file>[\w.]+\.csv)(?: row (?P<row>\d+))?(?:, (?P<col>\w+))?: (?P<msg>.*)$")


def _structure(problem: str) -> dict:
    m = _PROBLEM.match(problem)
    if not m:
        return {"file": None, "row": None, "column": None, "message": problem}
    return {"file": m["file"], "row": int(m["row"]) if m["row"] else None, "column": m["col"], "message": m["msg"]}


def _write(folder: Path, files: dict[str, str], slots: dict[str, str | None]) -> None:
    for slot, name in slots.items():
        if name and name in files and slot in SLOT_FILES:
            (folder / slot).write_text(files[name], encoding="utf-8")


def _summary(data: dict[str, list[dict]]) -> dict:
    quotes = data["quotes.csv"]
    status = {s: sum(1 for q in quotes if q["status"] == s) for s in ("open", "won", "lost", "expired")}
    dates = sorted(q["issued_date"] for q in quotes)
    return {
        "rows": {f: len(rows) for f, rows in data.items()},
        "quotes": status,
        "first_quote": dates[0] if dates else None,
        "last_quote": dates[-1] if dates else None,
        "computed_bases": sum(1 for r in data["quote_lines.csv"] if r["material_cost_basis"] is None),
    }


def check(files: dict[str, str], slots: dict[str, str | None] | None = None) -> dict:
    """Match, then validate without writing. `files` is {uploaded name: text}."""
    slots = {**match(list(files)), **(slots or {})}
    with tempfile.TemporaryDirectory() as tmp:
        _write(Path(tmp), files, slots)
        data, problems = importer.validate(Path(tmp))
    used = {n for n in slots.values() if n}
    return {
        "slots": [{"file": f, "label": label, "holds": holds, "uploaded": slots.get(f),
                   "rows": len(data[f]) if slots.get(f) else None} for f, label, holds, _ in SLOTS],
        "unused": [n for n in files if n not in used],
        "problems": [_structure(p) for p in problems],
        "valid": not problems,
        "summary": _summary(data) if not problems else None,
    }


# ------------------------------------------------------------------ the registry


def _registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"current": SAMPLE_ID, "shops": []}


def _save(reg: dict) -> None:
    SHOPS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def path_of(shop_id: str, sample_path: Path) -> Path:
    if shop_id == SAMPLE_ID:
        return Path(sample_path)
    shop = next((s for s in _registry()["shops"] if s["id"] == shop_id), None)
    if shop is None:
        raise KeyError(shop_id)
    return SHOPS_DIR / shop["file"]


def current_id() -> str:
    reg = _registry()
    ids = {s["id"] for s in reg["shops"]}
    return reg["current"] if reg["current"] in ids else SAMPLE_ID


def set_current(shop_id: str) -> None:
    reg = _registry()
    if shop_id != SAMPLE_ID and shop_id not in {s["id"] for s in reg["shops"]}:
        raise KeyError(shop_id)
    reg["current"] = shop_id
    _save(reg)


def _counts(path: Path) -> dict | None:
    if not path.exists():
        return None
    c = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        q = dict(c.execute("SELECT status, COUNT(*) FROM quotes GROUP BY status").fetchall())
        return {"open": q.get("open", 0), "won": q.get("won", 0),
                "customers": c.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
                "materials": c.execute("SELECT COUNT(*) FROM materials").fetchone()[0]}
    except sqlite3.Error:
        return None
    finally:
        c.close()


def listing(sample_path: Path) -> list[dict]:
    reg = _registry()
    out = [{"id": SAMPLE_ID, "name": "Sample shop", "synthetic": True, "created_at": None,
            "counts": _counts(Path(sample_path))}]
    for s in reg["shops"]:
        out.append({"id": s["id"], "name": s["name"], "synthetic": False, "created_at": s["created_at"],
                    "counts": _counts(SHOPS_DIR / s["file"])})
    return out


def create(name: str, files: dict[str, str], slots: dict[str, str | None] | None = None) -> dict:
    """Validate and load into a new database. Raises importer.ImportFailed, ValueError."""
    name = " ".join(name.split())
    if not name:
        raise ValueError("give the shop a name")
    reg = _registry()
    if name.lower() == "sample shop" or any(s["name"].lower() == name.lower() for s in reg["shops"]):
        raise ValueError(f"there is already a shop called {name!r}")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "shop"
    shop_id, n = slug, 2
    while shop_id in {s["id"] for s in reg["shops"]} or shop_id == SAMPLE_ID or (SHOPS_DIR / f"{shop_id}.db").exists():
        shop_id, n = f"{slug}-{n}", n + 1
    slots = {**match(list(files)), **(slots or {})}
    SHOPS_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOPS_DIR / f"{shop_id}.db"
    from . import db
    with tempfile.TemporaryDirectory() as tmp:
        _write(Path(tmp), files, slots)
        conn = db.connect(path)
        try:
            counts = importer.load(Path(tmp), conn)
        except Exception:
            conn.close()
            for suffix in ("", "-wal", "-shm"):
                Path(f"{path}{suffix}").unlink(missing_ok=True)
            raise
        conn.close()
    shop = {"id": shop_id, "name": name, "file": path.name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    reg["shops"].append(shop)
    reg["current"] = shop_id
    _save(reg)
    return {**shop, "rows": counts}


# ------------------------------------------------------------------ files to try it with


def sample_files(mistakes: bool = False) -> dict[str, str]:
    """The sample shop as its nine CSVs; with `mistakes`, four errors a real export might have."""
    files = {p.name: p.read_text(encoding="utf-8") for p in sorted(SAMPLE_FILES.glob("*.csv"))}
    if mistakes:
        files["material_vendors.csv"] = files["material_vendors.csv"].replace("MAT-CR-60,V-GLE,1", "MAT-CR-60,V-GLE,0", 1)
        files["quotes.csv"] = files["quotes.csv"].replace("Q-2026-0102,C-07,open,2026-10-13", "Q-2026-0102,C-07,open,10/13/2026", 1)
        files["customers.csv"] = files["customers.csv"].replace("C-01,Lakeshore HVAC,key,", "C-01,Lakeshore HVAC,gold,", 1)
        lines = files["quote_lines.csv"].splitlines(keepends=True)
        lines.insert(3, "Q-2026-0101,P-9999,100,2.50,,\n")
        files["quote_lines.csv"] = "".join(lines)
        files["Suppliers.csv"] = files.pop("vendors.csv")          # named the way a person would
    return files
