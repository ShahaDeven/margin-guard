"""A whole shop from the nine CSV files, through the console: matching the files, the
dry-run check, loading into a new database, and switching shops. The sample shop is
never written over."""

import json

import pytest

from margin_guard import importer, shops


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A shops folder of its own, so a test never touches data/shops."""
    monkeypatch.setattr(shops, "SHOPS_DIR", tmp_path / "shops")
    monkeypatch.setattr(shops, "REGISTRY", tmp_path / "shops" / "shops.json")
    return tmp_path


# ------------------------------------------------------------------ matching files to the nine slots


def test_files_are_matched_by_the_names_people_give_them():
    got = shops.match(["Suppliers.csv", "Bill of Materials.csv", "quote-lines.csv", "notes.csv", "Quotes.CSV"])
    assert got["vendors.csv"] == "Suppliers.csv"
    assert got["bom.csv"] == "Bill of Materials.csv"
    assert got["quote_lines.csv"] == "quote-lines.csv"
    assert got["quotes.csv"] == "Quotes.CSV"
    assert got["parts.csv"] is None


def test_a_slot_can_be_pointed_at_another_file_by_hand():
    files = shops.sample_files()
    files["export_7.csv"] = files.pop("parts.csv")
    r = shops.check(files)
    assert not r["valid"] and r["unused"] == ["export_7.csv"]
    assert {"file": "parts.csv", "row": None, "column": None, "message": "file missing"} in r["problems"]
    assert shops.check(files, {"parts.csv": "export_7.csv"})["valid"]


# ------------------------------------------------------------------ the check


def test_the_sample_files_check_clean_with_a_summary():
    r = shops.check(shops.sample_files())
    assert r["valid"] and not r["problems"] and not r["unused"]
    assert r["summary"]["quotes"] == {"open": 150, "won": 88, "lost": 32, "expired": 0}
    assert r["summary"]["rows"]["quote_lines.csv"] == 540
    assert [s["rows"] for s in r["slots"]][-1] == 540


def test_each_mistake_is_listed_once_by_file_row_and_column():
    r = shops.check(shops.sample_files(mistakes=True))
    assert not r["valid"] and r["summary"] is None
    assert r["problems"] == [
        {"file": "customers.csv", "row": 2, "column": "tier", "message": "'gold' must be one of key, standard"},
        {"file": "quotes.csv", "row": 3, "column": "issued_date", "message": "'10/13/2026' is not a date (YYYY-MM-DD)"},
        {"file": "quote_lines.csv", "row": 4, "column": "part_id", "message": "'P-9999' is not in parts.csv"},
        {"file": "materials.csv", "row": 3, "column": None,
         "message": "MAT-CR-60 has no costing supplier; mark exactly one in material_vendors.csv (is_costing = 1)"},
    ]       # not also "'C-01' is not in customers.csv" for each of that customer's 13 quotes


# ------------------------------------------------------------------ loading, and the registry


def test_a_valid_shop_loads_into_its_own_database_and_becomes_current(home):
    shop = shops.create("Acme Molding", shops.sample_files())
    assert shop["id"] == "acme-molding" and shop["rows"]["quotes.csv"] == 270
    assert (home / "shops" / "acme-molding.db").exists()
    assert shops.current_id() == "acme-molding"
    listed = {s["id"]: s for s in shops.listing(home / "sample.db")}
    assert listed["acme-molding"]["counts"] == {"open": 150, "won": 88, "customers": 24, "materials": 12}
    assert listed["sample"]["synthetic"] and listed["sample"]["counts"] is None      # no sample database here


def test_a_shop_with_problems_leaves_nothing_behind(home):
    with pytest.raises(importer.ImportFailed):
        shops.create("Broken", shops.sample_files(mistakes=True))
    assert not list((home / "shops").glob("*.db*"))
    assert shops.current_id() == shops.SAMPLE_ID


def test_names_are_unique_and_required(home):
    shops.create("Acme", shops.sample_files())
    for bad in ("acme", "Sample shop", "   "):
        with pytest.raises(ValueError):
            shops.create(bad, shops.sample_files())


def test_switching_back_to_the_sample_shop(home):
    shops.create("Acme", shops.sample_files())
    shops.set_current(shops.SAMPLE_ID)
    assert shops.current_id() == shops.SAMPLE_ID
    with pytest.raises(KeyError):
        shops.set_current("nope")


# ------------------------------------------------------------------ over HTTP


def test_the_console_flow_over_http(home, conn, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", conn)
    monkeypatch.setattr(api, "DB_PATH", home / "sample.db")
    monkeypatch.setattr(api, "SAMPLE_DB", home / "sample.db")
    monkeypatch.setattr(api, "_shop_resolved", True)
    with TestClient(api.app) as c:
        files = c.get("/api/shops/sample-files", params={"mistakes": True}).json()["files"]
        assert "Suppliers.csv" in files
        r = c.post("/api/shops/check", json={"files": files}).json()
        assert len(r["problems"]) == 4
        assert c.post("/api/shops", json={"name": "Broken", "files": files}).status_code == 400

        files = c.get("/api/shops/sample-files").json()["files"]
        shop = c.post("/api/shops", json={"name": "Acme Molding", "files": files}).json()
        assert api.DB_PATH == home / "shops" / "acme-molding.db"                 # the console now runs on it
        assert c.get("/api/shops").json()["current"] == shop["id"]
        assert c.get("/api/overview").status_code == 200

        assert c.post("/api/shops/sample/switch").json() == {"current": "sample"}
        assert api.DB_PATH == home / "sample.db"
        assert c.post("/api/shops/nope/switch").status_code == 404

        z = c.get("/api/shops/templates.zip")
        assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert json.loads((home / "shops" / "shops.json").read_text())["current"] == "sample"
