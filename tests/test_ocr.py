"""Scanned price sheets read by OCR (Tesseract): what is read, what counts as unreadable, and
the rule that every price read off a scan is checked by a person before it moves a quote.

The reading tests need Tesseract installed (they skip without it); the rules don't."""

import json

import pytest
from PIL import Image
from test_attachments import _att
from test_pipeline import _ch, _ex

from margin_guard import actions, attachments, db, ingest, ocr, seed
from margin_guard.actions import ActionError
from margin_guard.config import ROOT
from margin_guard.parser import normalize

SET = ROOT / "data" / "vendor_emails_ocr.json"
FILES = ROOT / "data" / "attachments"
FAX = "midwest_price_sheet_fax_jan2027.pdf"
PHOTO = "fluorotech_letter_photo.jpg"

needs_tesseract = pytest.mark.skipif(ocr.tesseract() is None, reason="Tesseract is not installed")

# What a perfect reader reports from each scan, so the code's rules are what's tested.
PERFECT = {
    "O01": _ex("price_change", [
        _att("EPDM 50", 2.04, "lb", "2027-01-01"),
        _att("EPDM 60", 2.15, "lb", "2027-01-01"),
        _att("EPDM 80", 2.42, "lb", "2027-01-01"),      # not a material we buy
        _att("SBR 60", 1.62, "lb", "2027-01-01"),       # unchanged
        _att("NR 40", 1.97, "lb", "2027-01-01"),
    ]),
    "O02": _ex("price_change", [_att("FKM 75 fluoroelastomer compound", 33.50, "kg", "2027-02-01")]),
    "O03": _ex("price_advisory"),
}


@pytest.fixture
def shop(tmp_path):
    c = db.connect(tmp_path / "ocr.db")
    seed.build(c, SET)
    yield c
    c.close()


# ------------------------------------------------------------------ reading scans


@needs_tesseract
def test_a_faxed_sheet_is_read_by_ocr_with_its_confidence():
    r = attachments.render(FAX, (FILES / FAX).read_bytes())
    assert r.state == attachments.OCR
    assert "read by OCR, mean word confidence" in r.note
    for row in ("EPDM 50 1.95 2.04", "EPDM 60 2.05 2.15", "NR 40 1.88 1.97"):
        assert row in r.text
    assert "January 1, 2027" in r.text


@needs_tesseract
def test_a_phone_photo_is_read_by_ocr():
    r = attachments.render(PHOTO, (FILES / PHOTO).read_bytes())
    assert r.state == attachments.OCR and attachments.content_type(PHOTO) == "image/jpeg"
    assert "$33.50/kg" in r.text and "February 1, 2027" in r.text


@needs_tesseract
def test_a_blank_image_is_unreadable_not_guessed(tmp_path):
    import io
    buf = io.BytesIO()
    Image.new("L", (1200, 900), 255).save(buf, "PNG")
    r = attachments.render("blank.png", buf.getvalue())
    assert r.state == attachments.UNREADABLE and "couldn't read" in r.note and r.text == ""


def test_a_scan_with_no_image_is_unreadable():
    r = attachments.render("s.pdf", (FILES / "summit_price_sheet_scan.pdf").read_bytes())
    assert r.state == attachments.UNREADABLE and "no text layer" in r.note


def test_without_tesseract_a_scan_is_unreadable_and_says_why(monkeypatch):
    monkeypatch.setattr(ocr, "tesseract", lambda: None)
    r = attachments.render(FAX, (FILES / FAX).read_bytes())
    assert r.state == attachments.UNREADABLE and "isn't installed" in r.note


def test_the_prompt_says_the_text_came_from_ocr():
    block = attachments.for_prompt([("fax.pdf", attachments.Rendered("EPDM 50 2.04", "read by OCR, mean word confidence 94%",
                                                                     attachments.OCR))])
    assert "read by OCR" in block and "do not correct it" in block


# ------------------------------------------------------------------ the rule: a person checks every OCR price


def _email(**kw):
    return {"id": "T1", "from_addr": "pricing@midwestpolymer.com",
            "ocr_attachments": [("fax.pdf", "read by OCR, mean word confidence 94%")], **kw}


def test_an_ocr_price_goes_to_a_person_not_straight_to_the_agents(conn):
    r = normalize(conn, _email(), _ex("price_change", [_att("EPDM 50", 2.04, "lb", "2027-01-01")]))
    [d] = r.drafts
    assert d.event_type == "price_change.needs_review"
    assert any("read by OCR from fax.pdf" in x for x in d.payload["review_reasons"])
    assert d.payload["ocr"]["files"] == ["fax.pdf"] and d.payload["new_cost_per_lb"] == 2.04


def test_the_rule_holds_whatever_part_of_the_email_the_model_says_the_price_came_from(conn):
    r = normalize(conn, _email(), _ex("price_change", [_ch("EPDM 50", 2.04, "lb", "2027-01-01")]))   # source "email"
    assert [d.event_type for d in r.drafts] == ["price_change.needs_review"]


def test_a_scan_that_gave_no_price_is_read_by_a_person(conn):
    r = normalize(conn, _email(), _ex("other"))
    [d] = r.drafts
    assert d.event_type == "price_change.needs_review" and d.payload["kind"] == "ocr_no_prices"


def test_a_faxed_sheet_becomes_one_check_per_price_we_buy(shop):
    ingest.run(shop, extract=lambda e: PERFECT[e["id"]])
    rows = [json.loads(r["payload"]) for r in shop.execute(
        "SELECT payload FROM events WHERE source_ref = 'email:O01' ORDER BY id")]
    assert {r["material_id"] for r in rows} == {"MAT-EPDM-50", "MAT-EPDM-60", "MAT-NR-40"}   # SBR unchanged, EPDM 80 not ours
    assert not shop.execute("SELECT 1 FROM events WHERE event_type = 'price_change.detected' AND source_ref LIKE 'email:%'").fetchone()
    assert {r[0] for r in shop.execute("SELECT outcome FROM inbox_emails")} == {"needs_review"}


# ------------------------------------------------------------------ correcting what OCR misread


def _review(conn, email_id):
    return conn.execute(
        "SELECT p.id FROM proposals p JOIN events e ON e.id = p.event_id WHERE e.source_ref = ? ORDER BY p.id",
        (f"email:{email_id}",)).fetchone()["id"]


@pytest.fixture
def checked(shop):
    from margin_guard import coordinator
    from test_coordinator import POLICY_DECIDER
    ingest.run(shop, extract=lambda e: PERFECT[e["id"]])
    coordinator.run(shop, POLICY_DECIDER)
    return shop


def test_the_figures_as_read_can_be_applied(checked):
    ev = actions.resolve_review(checked, _review(checked, "O02"), "MAT-FKM-75")
    p = json.loads(checked.execute("SELECT payload FROM events WHERE id = ?", (ev,)).fetchone()[0])
    assert p["new_cost_per_lb"] == 15.195344 and "corrected_by_person" not in p


def test_a_misread_price_is_corrected_in_the_suppliers_unit(checked):
    pid = _review(checked, "O02")
    ev = actions.resolve_review(checked, pid, "MAT-FKM-75", price=33.05, effective_date="2027-02-15")
    p = json.loads(checked.execute("SELECT payload FROM events WHERE id = ?", (ev,)).fetchone()[0])
    assert p["new_cost_per_lb"] == 14.991228 and p["effective_date"] == "2027-02-15"     # $33.05/kg
    assert p["corrected_by_person"]["price"] == {"was": 15.195344, "now": 14.991228, "quoted": 33.05, "unit": "kg"}
    assert "Corrected the figures" in checked.execute("SELECT reviewer_note FROM proposals WHERE id = ?", (pid,)).fetchone()[0]


def test_a_correction_must_be_a_price_and_a_date(checked):
    pid = _review(checked, "O02")
    with pytest.raises(ActionError):
        actions.resolve_review(checked, pid, "MAT-FKM-75", price=0)
    with pytest.raises(ActionError):
        actions.resolve_review(checked, pid, "MAT-FKM-75", effective_date="Feb 1")


def test_a_database_built_before_ocr_is_migrated_with_its_attachments(tmp_path):
    c = db.connect(tmp_path / "old.db")
    seed.build(c, ROOT / "data" / "vendor_emails_attachments.json")         # attachments, none read by OCR
    old_sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'email_attachments'").fetchone()[0]
    rows = c.execute("SELECT * FROM email_attachments ORDER BY id").fetchall()
    c.executescript("DROP INDEX idx_attachments_email; ALTER TABLE email_attachments RENAME TO x; "
                    + old_sql.replace("'OCR', ", "") + "; INSERT INTO email_attachments SELECT * FROM x; DROP TABLE x;"
                    "CREATE INDEX idx_attachments_email ON email_attachments(email_id);")
    assert "'OCR'" not in c.execute("SELECT sql FROM sqlite_master WHERE name = 'email_attachments'").fetchone()[0]
    db.init_schema(c)
    assert [tuple(r) for r in c.execute("SELECT * FROM email_attachments ORDER BY id")] == [tuple(r) for r in rows]
    c.execute("INSERT INTO email_attachments (email_id, filename, content_type, data, state) "
              "VALUES ('A01', 'fax.pdf', 'application/pdf', x'00', 'OCR')")             # an OCR state now fits
    assert c.execute("SELECT 1 FROM sqlite_master WHERE name = 'idx_attachments_email'").fetchone()
    c.close()


@needs_tesseract
def test_claudes_cached_reading_of_the_scans_puts_every_gold_price_in_front_of_a_person(shop):
    """Replays the live eval (evals/results/extractions_ocr.json) through OCR and the rules."""
    from margin_guard.parser import EmailExtraction
    cache = json.loads((ROOT / "evals" / "results" / "extractions_ocr.json").read_text(encoding="utf-8"))
    ingest.run(shop, extract=lambda e: EmailExtraction.model_validate(cache[e["id"]]))
    for e in json.loads(SET.read_text(encoding="utf-8")):
        got = {p["material_id"]: p for p in (json.loads(r[0]) for r in shop.execute(
            "SELECT payload FROM events WHERE source_ref = ? AND event_type = 'price_change.needs_review'", (f"email:{e['id']}",)))
            if p.get("material_id")}
        assert set(got) == {g["material_id"] for g in e["gold"]["changes"]}
        for g in e["gold"]["changes"]:
            assert abs(got[g["material_id"]]["new_cost_per_lb"] - g["new_cost_per_lb"]) < 0.005 * g["new_cost_per_lb"]
            assert got[g["material_id"]]["effective_date"] == g["effective_date"]


def test_a_correction_over_http(checked, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", checked)
    monkeypatch.setattr(api, "_run_job", lambda name, work: None)          # the agents' run is tested elsewhere
    pid = _review(checked, "O02")
    with TestClient(api.app) as c:
        r = c.post(f"/api/proposals/{pid}/resolve", json={"material_id": "MAT-FKM-75", "price": 33.05,
                                                          "effective_date": "2027-02-15"})
        assert r.status_code == 200
        p = json.loads(checked.execute("SELECT payload FROM events WHERE id = ?", (r.json()["event_id"],)).fetchone()[0])
        assert p["new_cost_per_lb"] == 14.991228 and p["effective_date"] == "2027-02-15"
        assert c.post(f"/api/proposals/{_review(checked, 'O01')}/resolve",
                      json={"material_id": "MAT-EPDM-50", "price": -1}).status_code == 400


def test_done_shows_what_an_answered_scan_became(checked, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", checked)
    pid = _review(checked, "O02")
    ev = actions.resolve_review(checked, pid, "MAT-FKM-75", price=33.05)
    with TestClient(api.app) as c:
        row = next(r for r in c.get("/api/queue", params={"lane": "done"}).json() if r["id"] == pid)
    assert row["resolved"]["event_id"] == ev and row["resolved"]["new_cost_per_lb"] == 14.991228
    assert row["resolved"]["corrected_by_person"]["price"]["quoted"] == 33.05
