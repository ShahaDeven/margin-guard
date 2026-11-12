"""Console invoice import: stage -> map -> match -> dry-run preview -> one-transaction commit -> history."""

import pytest

from margin_guard import catalog, imports, invoices
from margin_guard.config import ROOT

AP = ROOT / "data" / "invoices_ap_export.csv"
DEMO = ROOT / "data" / "invoices_demo.csv"
SUPPLIERS = {"GLE": "V-GLE"}
MATCHES = {"V-MWP|EPM70 BLK": "MAT-EPDM-70", "V-RCB|Freight": invoices.NOT_STOCKED}


def _stage(conn, text=None, name="invoices_ap_export.csv"):
    return imports.stage(conn, name, text if text is not None else AP.read_text(encoding="utf-8"))


def _counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("invoice_lines", "events", "proposals")} | {
        "aliases": conn.execute("SELECT group_concat(aliases) FROM materials").fetchone()[0]}


# ------------------------------------------------------------------ mapping, matching, normalizing


def test_mapping_is_suggested_from_an_ap_export_header(conn):
    staged = _stage(conn)
    assert staged["mapping"] == {
        "invoice_no": "Doc No", "line_no": "Ln", "invoice_date": "Posting Date", "supplier": "Vendor Name",
        "item": "Description", "qty": "Qty Billed", "unit": "UoM", "unit_price": "Price Each", "pack_qty": "Pack"}
    assert staged["row_count"] == 8 and len(staged["sample"]) == 5


def test_canonical_headers_map_to_themselves():
    headers = ["invoice_no", "line_no", "invoice_date", "vendor_id", "item", "qty", "unit", "unit_price", "pack_qty"]
    m = imports.suggest_mapping(headers)
    assert m["supplier"] == "vendor_id" and m["unit_price"] == "unit_price" and m["pack_qty"] == "pack_qty"
    assert len({v for v in m.values()}) == len(m)                    # no column used twice


def test_supplier_matching_by_id_name_domain_and_partial_name(conn):
    assert imports.match_supplier(conn, "V-MWP") == "V-MWP"
    assert imports.match_supplier(conn, "Summit Silicones") == "V-SUM"
    assert imports.match_supplier(conn, "ridgelinecarbon.com") == "V-RCB"
    assert imports.match_supplier(conn, "Midwest Polymer") == "V-MWP"
    assert imports.match_supplier(conn, "GLE") is None               # an abbreviation is asked about, not guessed
    assert imports.match_supplier(conn, "") is None


def test_dates_and_units_are_normalized():
    assert imports._date("10/12/2026") == "2026-10-12"
    assert imports._date("12-Oct-2026") == "2026-10-12"
    assert imports._date("someday") == "someday"                     # left for the validator to report
    assert imports.UNITS["lbs"] == "lb" and imports.UNITS["ton"] == "short_ton" and imports.UNITS["mt"] == "metric_ton"


# ------------------------------------------------------------------ stage limits


@pytest.mark.parametrize("text, message", [
    ("Doc No,Ln\n", "at least one invoice line"),
    ("Doc No,Doc No\nA,1\n", "distinct, non-empty header"),
    ("Doc No,\nA,1\n", "distinct, non-empty header"),
])
def test_bad_files_are_refused_at_upload(conn, text, message):
    with pytest.raises(imports.ImportError_, match=message):
        imports.stage(conn, "bad.csv", text)
    assert conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0] == 0


def test_size_and_row_limits(conn, monkeypatch):
    monkeypatch.setattr(imports, "MAX_ROWS", 2)
    with pytest.raises(imports.ImportError_, match="the limit is 2"):
        imports.stage(conn, "big.csv", "a,b\n1,2\n3,4\n5,6\n")
    monkeypatch.setattr(imports, "MAX_BYTES", 10)
    with pytest.raises(imports.ImportError_, match="over"):
        imports.stage(conn, "big.csv", "a,b\n1,2\n3,4\n")


# ------------------------------------------------------------------ preview stages


def test_preview_walks_mapping_then_suppliers_then_ready(conn):
    staged = _stage(conn)
    mapping = staged["mapping"]

    p = imports.preview(conn, staged["import_id"], {**mapping, "qty": None})
    assert p["stage"] == "mapping" and "Quantity" in p["problems"][0]

    p = imports.preview(conn, staged["import_id"], {**mapping, "qty": "Qty Shipped"})
    assert p["stage"] == "mapping" and "Qty Shipped" in p["problems"][0]

    p = imports.preview(conn, staged["import_id"], mapping)
    assert p["stage"] == "suppliers" and p["problems"] == ["match the supplier 'GLE' to one on file"]
    assert {s["text"]: s["vendor_id"] for s in p["suppliers"]}["Midwest Polymer"] == "V-MWP"

    p = imports.preview(conn, staged["import_id"], mapping, SUPPLIERS)
    assert p["stage"] == "ready"
    asked = {i["key"] for i in p["items"] if not i["auto"]}
    assert asked == {"V-MWP|EPM70 BLK", "V-RCB|Freight"}


def test_preview_reports_row_errors(conn):
    text = ("Doc No,Ln,Posting Date,Vendor Name,Description,Qty Billed,UoM,Price Each\n"
            "X-1,1,10/12/2026,Ridgeline Carbon,N-550 carbon black,lots,CWT,114.00\n"
            "X-1,2,someday,Ridgeline Carbon,N-550 carbon black,3,CWT,114.00\n")
    staged = _stage(conn, text, "bad.csv")
    p = imports.preview(conn, staged["import_id"], staged["mapping"])
    assert p["stage"] == "errors" and len(p["problems"]) >= 2
    assert "summary" not in p


def test_preview_is_a_dry_run(conn):
    staged = _stage(conn)
    before = _counts(conn)
    p = imports.preview(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)
    assert _counts(conn) == before
    s = p["summary"]
    assert (s["lines"], s["at_price"], s["above"], s["not_judged"]) == (8, 4, 3, 1)
    assert s["overpaid_usd"] == pytest.approx(495.93)
    dates = {line["date"] for line in p["lines"]}
    assert dates <= {"2026-10-12", "2026-10-13", "2026-10-14"}       # US dates normalized


# ------------------------------------------------------------------ commit


def test_commit_matches_the_preview_and_records_history(conn):
    staged = _stage(conn)
    preview = imports.preview(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)
    result = imports.commit(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)
    assert {k: v for k, v in result["summary"].items() if k != "remembered"} == preview["summary"]
    assert conn.execute("SELECT COUNT(*) FROM invoice_lines").fetchone()[0] == 8

    row = imports.history(conn)[0]
    assert row["status"] == "committed" and row["committed_at"] and row["summary"]["above"] == 3

    with pytest.raises(imports.ImportError_, match="already committed"):
        imports.commit(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)


def test_commit_refuses_an_unready_import(conn):
    staged = _stage(conn)
    with pytest.raises(imports.ImportError_, match="GLE"):
        imports.commit(conn, staged["import_id"], staged["mapping"])
    assert conn.execute("SELECT COUNT(*) FROM invoice_lines").fetchone()[0] == 0
    assert imports.history(conn)[0]["status"] == "staged"


def test_commit_is_all_or_nothing(conn, monkeypatch):
    staged = _stage(conn)
    before = _counts(conn)

    def boom(*_a, **_k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(imports, "_remember", boom)
    with pytest.raises(RuntimeError):
        imports.commit(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES, remember=True)
    assert _counts(conn) == before
    assert imports.history(conn)[0]["status"] == "staged"


def test_remembered_match_works_next_time(conn):
    assert catalog.resolve_material(conn, "EPM70 BLK", "V-MWP").material_id is None
    staged = _stage(conn)
    result = imports.commit(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES, remember=True)
    assert result["summary"]["remembered"] == ["'epm70 blk' -> MAT-EPDM-70"]
    assert catalog.resolve_material(conn, "EPM70 BLK", "V-MWP").material_id == "MAT-EPDM-70"


def test_not_remembered_unless_asked(conn):
    staged = _stage(conn)
    imports.commit(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)
    assert catalog.resolve_material(conn, "EPM70 BLK", "V-MWP").material_id is None


def test_import_adds_to_an_open_drift_card(conn):
    invoices.check(conn, DEMO)                                       # opens a card for N550 at Ridgeline
    staged = _stage(conn)
    p = imports.preview(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)
    drifts = {d["material_id"]: d["status"] for d in p["summary"]["drifts"]}
    assert drifts.get("MAT-CB-N550") == "merged" and p["summary"]["cards_merged"] >= 1


def test_discard(conn):
    staged = _stage(conn)
    imports.discard(conn, staged["import_id"])
    assert imports.history(conn)[0]["status"] == "discarded"
    with pytest.raises(imports.ImportError_, match="already discarded"):
        imports.preview(conn, staged["import_id"], staged["mapping"], SUPPLIERS, MATCHES)
    with pytest.raises(imports.ImportError_, match="not found"):
        imports.discard(conn, 999)


# ------------------------------------------------------------------ HTTP


@pytest.fixture
def client(conn, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", conn)
    monkeypatch.setattr(api, "_run_job", lambda *_a, **_k: None)    # the coordinator is tested elsewhere
    with TestClient(api.app) as c:
        yield c


def test_import_over_http(client):
    demo = client.get("/api/imports/demo/invoices_ap_export.csv").json()
    assert client.get("/api/imports/demo/..%2Fmargin_guard.db").status_code == 404

    staged = client.post("/api/imports/invoices", json={"filename": demo["filename"], "text": demo["text"]}).json()
    plan = {"mapping": staged["mapping"], "suppliers": SUPPLIERS, "matches": MATCHES, "remember": False}
    preview = client.post(f"/api/imports/{staged['import_id']}/preview", json=plan).json()
    assert preview["stage"] == "ready" and preview["summary"]["lines"] == 8

    done = client.post(f"/api/imports/{staged['import_id']}/commit", json=plan).json()
    assert done["summary"]["above"] == 3
    again = client.post(f"/api/imports/{staged['import_id']}/commit", json=plan)
    assert again.status_code == 400 and "already committed" in again.json()["detail"]

    history = client.get("/api/imports").json()
    assert history[0]["status"] == "committed" and history[0]["filename"] == "invoices_ap_export.csv"
    assert any(v["id"] == "V-GLE" for v in client.get("/api/vendors").json())


def test_bad_upload_is_a_400(client):
    r = client.post("/api/imports/invoices", json={"filename": "x.csv", "text": "only,a,header\n"})
    assert r.status_code == 400
