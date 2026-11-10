"""CSV import: an exact round trip, and all-or-nothing validation with usable messages."""

import csv

import pytest

from margin_guard import db, importer, leakage

TABLES = {
    "quotes": "*",
    "quote_lines": "quote_id, part_id, qty, unit_price, material_cost_basis, conversion_cost",
    "material_price_history": "material_id, vendor_id, cost_per_lb, effective_date",
    "materials": "*", "material_vendors": "*", "part_materials": "*", "parts": "*",
    "customers": "*", "vendors": "*",
}


@pytest.fixture
def folder(conn, tmp_path):
    out = tmp_path / "csv"
    importer.export(conn, out)
    return out


def _edit(folder, file, change):
    """Rewrite one CSV: `change(rows)` mutates the list of dicts (header kept)."""
    path = folder / file
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header, rows = list(reader.fieldnames), list(reader)
    change(rows)
    if rows:   # a dropped column leaves the header; an added one joins it
        header = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def _problems(folder):
    return importer.validate(folder)[1]


def test_round_trip_is_exact(conn, folder, tmp_path):
    other = db.connect(tmp_path / "imported.db")
    importer.load(folder, other)
    for table, cols in TABLES.items():
        q = f"SELECT {cols} FROM {table} ORDER BY 1, 2"
        assert [tuple(r) for r in conn.execute(q)] == [tuple(r) for r in other.execute(q)], table
    assert leakage.analyze(other)["net_leaked_usd"] == leakage.analyze(conn)["net_leaked_usd"]


def test_exported_templates_are_valid(folder):
    assert _problems(folder) == []


def test_a_bad_file_imports_nothing(folder, tmp_path):
    _edit(folder, "quotes.csv", lambda rows: rows[0].update(issued_date="13/10/2026"))
    target = db.connect(tmp_path / "new.db")
    with pytest.raises(importer.ImportFailed) as exc:
        importer.load(folder, target)
    assert any("quotes.csv row 2, issued_date" in p for p in exc.value.problems)
    assert target.execute("SELECT name FROM sqlite_master WHERE name = 'quotes'").fetchone() is None


@pytest.mark.parametrize("file, change, expected", [
    ("bom.csv", lambda r: r[0].update(material_id="MAT-NOPE"), "bom.csv row 2, material_id: 'MAT-NOPE' is not in"),
    ("materials.csv", lambda r: r[1].update(id=r[0]["id"]), "materials.csv row 3: duplicate id"),
    ("materials.csv", lambda r: r[0].update(cost_per_lb="-1.20"), "materials.csv row 2, cost_per_lb: -1.20 must be"),
    ("quotes.csv", lambda r: r[0].update(margin_floor="25"), "quotes.csv row 2, margin_floor: 25 must be a fraction"),
    ("quotes.csv", lambda r: r[0].update(status="pending"), "quotes.csv row 2, status: 'pending' must be one of"),
    ("quote_lines.csv", lambda r: r[0].update(qty="2.5"), "quote_lines.csv row 2, qty: 2.5 must be a whole number"),
    ("quote_lines.csv", lambda r: r[0].update(quote_id="Q-NOPE"), "quote_lines.csv row 2, quote_id: 'Q-NOPE'"),
    ("material_vendors.csv", lambda r: [x.update(is_costing="1") for x in r if x["material_id"] == "MAT-EPDM-70"],
     "MAT-EPDM-70 has 2 costing suppliers"),
    ("price_history.csv", lambda r: r[0].update(vendor_id="V-KRD"), "isn't listed as a supplier of"),
])
def test_each_problem_names_file_row_and_column(folder, file, change, expected):
    _edit(folder, file, change)
    problems = _problems(folder)
    assert any(expected in p for p in problems), problems


def test_won_quote_needs_an_order_date(folder):
    def drop(rows):
        next(r for r in rows if r["status"] == "won")["ordered_date"] = ""
    _edit(folder, "quotes.csv", drop)
    assert any("a won quote needs an ordered_date" in p for p in _problems(folder))


def test_order_before_quote_is_rejected(folder):
    def back(rows):
        r = next(r for r in rows if r["status"] == "won")
        r["ordered_date"] = "2020-01-01"
    _edit(folder, "quotes.csv", back)
    assert any("ordered_date is before issued_date" in p for p in _problems(folder))


def test_missing_file_and_column(folder):
    (folder / "bom.csv").unlink()
    _edit(folder, "parts.csv", lambda rows: [r.pop("conversion_cost") for r in rows])
    problems = _problems(folder)
    assert "bom.csv: file missing" in problems
    assert any("parts.csv: missing column(s) conversion_cost" in p for p in problems)


def test_money_cells_accept_dollar_signs_and_commas(folder, tmp_path):
    _edit(folder, "quote_lines.csv", lambda rows: rows[0].update(unit_price="$1,234.5"))
    other = db.connect(tmp_path / "new.db")
    importer.load(folder, other)
    first = other.execute("SELECT unit_price FROM quote_lines ORDER BY quote_id, id LIMIT 1").fetchone()[0]
    assert first == 1234.5


def test_blank_cost_basis_is_computed_from_history(conn, folder, tmp_path):
    def blank(rows):
        for r in rows:
            r["material_cost_basis"] = ""
            r["conversion_cost"] = ""
    _edit(folder, "quote_lines.csv", blank)
    other = db.connect(tmp_path / "new.db")
    importer.load(folder, other)
    q = "SELECT material_cost_basis, conversion_cost FROM quote_lines ORDER BY quote_id, id"
    for (basis, conv), (b2, c2) in zip(conn.execute(q), other.execute(q)):
        assert b2 == pytest.approx(basis, abs=1e-4) and c2 == conv


def test_blank_basis_without_history_is_refused(folder):
    _edit(folder, "price_history.csv", lambda rows: rows.clear())
    _edit(folder, "quote_lines.csv", lambda rows: rows[0].update(material_cost_basis=""))
    assert any("material_cost_basis is blank" in p for p in _problems(folder))


def test_import_refuses_a_database_that_has_quotes(conn, folder):
    with pytest.raises(importer.ImportFailed, match="nothing was imported"):
        importer.load(folder, conn)


def test_shipped_templates_match_the_demo_shop(conn, tmp_path):
    from margin_guard.config import ROOT
    shipped = ROOT / "data" / "shop_csv"
    fresh = tmp_path / "fresh"
    importer.export(conn, fresh)
    for f in sorted(p.name for p in fresh.iterdir()):
        assert (shipped / f).read_text(encoding="utf-8") == (fresh / f).read_text(encoding="utf-8"), f
