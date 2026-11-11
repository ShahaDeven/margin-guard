"""Price lists and letters as attachments: reading them, extracting from them, and
the rules for rows we don't buy, unchanged rows and files that can't be read."""

import json

import pytest
from test_pipeline import _ch, _ex

from margin_guard import attachments, catalog, db, ingest, seed
from margin_guard.config import ROOT
from margin_guard.parser import EmailExtraction, normalize

SET = ROOT / "data" / "vendor_emails_attachments.json"
FILES = ROOT / "data" / "attachments"


def _att(text, price=None, unit=None, date=None):
    return _ch(text, price, unit, date).model_copy(update={"source": "attachment"})


# What a perfect reader reports for each email in the attachment set, rows we
# don't buy and unchanged rows included, so the code's own rules are what's tested.
PERFECT = {
    "A01": _ex("price_change", [
        _att("NBR 70", 5.20, "kg", "2026-12-01"),
        _att("NBR 90", 5.47, "kg", "2026-12-01"),       # unchanged (rounds to 0.05% in $/lb)
        _att("CR 60", 7.95, "kg", "2026-12-01"),
        _att("HNBR 80", 19.30, "kg", "2026-12-01"),     # not a material we buy
        _att("ECO 70", 11.65, "kg", "2026-12-01"),      # not a material we buy
    ]),
    "A02": _ex("price_change", [
        _att("N550", 121.0, "cwt", "2027-01-01"),
        _att("Carbon black N330", 126.5, "cwt", "2027-01-01"),   # must not become N550
    ]),
    "A03": _ex("price_advisory"),
    "A04": _ex("price_change", [
        _att("1018 CR bar", 1820.0, "short_ton", "2026-12-15"),
        _att("1045 CR bar", 1940.0, "short_ton", "2026-12-15"),
    ]),
}


@pytest.fixture
def shop(tmp_path):
    c = db.connect(tmp_path / "att.db")
    seed.build(c, SET)
    yield c
    c.close()


@pytest.fixture(scope="module")
def gold():
    return {e["id"]: e for e in json.loads(SET.read_text(encoding="utf-8"))}


# ------------------------------------------------------------------ reading files


def test_excel_sheets_become_rows():
    r = attachments.render("gle.xlsx", (FILES / "gle_price_list_dec2026.xlsx").read_bytes())
    assert r.note is None
    assert "[sheet: December 2026]" in r.text
    assert "NBR 70 | Nitrile 70 Shore A, black | 4.96 | 5.2 | +4.8%" in r.text


def test_every_sheet_is_read():
    r = attachments.render("b.xlsx", (FILES / "buckeye_bar_pricing_dec2026.xlsx").read_bytes())
    assert "[sheet: Read me]" in r.text and "December 15, 2026" in r.text
    assert "[sheet: Prices]" in r.text and "1018 CR bar" in r.text


def test_pdf_text_layer_is_read():
    r = attachments.render("n.pdf", (FILES / "ridgeline_price_notice_jan2027.pdf").read_bytes())
    assert "N550" in r.text and "121.00" in r.text and r.note is None


def test_scanned_pdf_is_flagged_not_guessed():
    r = attachments.render("s.pdf", (FILES / "summit_price_sheet_scan.pdf").read_bytes())
    assert r.text == "" and "no text layer" in r.note


def test_unreadable_and_unknown_files_say_why():
    assert "not read" in attachments.render("photo.jpg", b"\xff\xd8").note
    assert "could not read" in attachments.render("broken.xlsx", b"not a zip").note


def test_csv_is_read():
    r = attachments.render("p.csv", b"Grade,New price\nNBR 70,5.20\n")
    assert r.text == "Grade | New price\nNBR 70 | 5.20"


def test_long_lists_are_cut_and_say_so():
    rows = "\n".join(f"G{i},{i}" for i in range(attachments.MAX_ROWS + 50)).encode()
    r = attachments.render("long.csv", rows)
    assert r.text.count("\n") == attachments.MAX_ROWS - 1 and "cut at" in r.note


# ------------------------------------------------------------------ pipeline


def test_seed_stores_attachments(shop):
    rows = shop.execute("SELECT email_id, filename, note FROM email_attachments ORDER BY email_id").fetchall()
    assert [r["email_id"] for r in rows] == ["A01", "A02", "A03", "A04"]
    assert rows[2]["note"] and "no text layer" in rows[2]["note"]


def test_extractor_sees_the_attachment_text(shop):
    seen = {}

    def extract(email):
        seen[email["id"]] = email.get("attachments_text", "")
        return PERFECT[email["id"]]
    ingest.run(shop, extract=extract)
    assert "--- Attachment: gle_price_list_dec2026.xlsx ---" in seen["A01"] and "CR 60" in seen["A01"]
    assert "N550" in seen["A02"]
    assert "could not be read" in seen["A03"]


def test_perfect_reader_reproduces_gold(shop, gold):
    outcomes = ingest.run(shop, extract=lambda e: PERFECT[e["id"]])
    assert outcomes == {i: g["gold"]["outcome"] for i, g in gold.items()}
    for email_id, g in gold.items():
        got = {p["material_id"]: p for p in (json.loads(r["payload"]) for r in shop.execute(
            "SELECT payload FROM events WHERE source_ref = ? AND event_type = 'price_change.detected'",
            (f"email:{email_id}",)))}
        assert set(got) == {c["material_id"] for c in g["gold"]["changes"]}, email_id
        for c in g["gold"]["changes"]:
            assert got[c["material_id"]]["new_cost_per_lb"] == pytest.approx(c["new_cost_per_lb"], rel=5e-4)
            assert got[c["material_id"]]["effective_date"] == c["effective_date"]


def test_rows_we_dont_buy_and_unchanged_rows_are_noted_not_reviewed(shop):
    ingest.run(shop, extract=lambda e: PERFECT[e["id"]])
    note = shop.execute("SELECT note FROM inbox_emails WHERE id = 'A01'").fetchone()[0]
    assert "HNBR 80" in note and "ECO 70" in note and "NBR 90: price unchanged" in note
    assert shop.execute("SELECT COUNT(*) FROM events WHERE event_type = 'price_change.needs_review'"
                        " AND source_ref = 'email:A01'").fetchone()[0] == 0


def test_scanned_attachment_goes_to_a_person_with_the_reason(shop):
    ingest.run(shop, extract=lambda e: PERFECT[e["id"]])
    ev = shop.execute("SELECT payload FROM events WHERE source_ref = 'email:A03'").fetchone()
    reasons = json.loads(ev["payload"])["review_reasons"]
    assert any("summit_price_sheet_scan.pdf" in r and "no text layer" in r for r in reasons)


def test_a_list_with_nothing_we_buy_is_ignored(conn):
    email = {"id": "T1", "from_addr": "sales@glelastomers.com"}
    result = normalize(conn, email, _ex("price_change", [_att("HNBR 80", 19.3, "kg", "2026-12-01")]))
    assert not result.drafts and "no changes to materials we buy" in result.ignored_reason


def test_unknown_material_in_the_email_text_still_goes_to_a_person(conn):
    # Only price-list rows are skipped; a material named in the email itself is a question.
    email = {"id": "T2", "from_addr": "sales@glelastomers.com"}
    [draft] = normalize(conn, email, _ex("price_change", [_ch("HNBR 80", 19.3, "kg", "2026-12-01")])).drafts
    assert draft.event_type == "price_change.needs_review"


def test_cached_extractions_without_source_still_load():
    ex = EmailExtraction.model_validate({"email_kind": "price_change", "confidence": 0.9, "rationale": "r",
                                         "changes": [{"material_text": "N550", "new_price": 1.2, "price_unit": "lb",
                                                      "pack_qty": None, "old_price": None, "pct_change": None,
                                                      "effective_date": "2027-01-01"}]})
    assert ex.changes[0].source == "email"


# ------------------------------------------------------------------ catalog


def test_generic_family_name_does_not_claim_another_grade(conn):
    assert catalog.resolve_material(conn, "Carbon black N330", "V-RCB").material_id is None
    assert catalog.resolve_material(conn, "N550 carbon black", "V-RCB").material_id == "MAT-CB-N550"
    assert catalog.resolve_material(conn, "carbon black", "V-RCB").material_id == "MAT-CB-N550"


# ------------------------------------------------------------------ API


def test_api_lists_and_serves_attachments(shop, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", shop)
    with TestClient(api.app) as c:
        mail = {m["id"]: m for m in c.get("/api/inbox").json()}
        [a] = mail["A01"]["attachments"]
        assert a["filename"] == "gle_price_list_dec2026.xlsx" and a["note"] is None
        assert "no text layer" in mail["A03"]["attachments"][0]["note"]
        res = c.get(f"/api/attachments/{a['id']}")
        assert res.status_code == 200 and res.content == (FILES / a["filename"]).read_bytes()
        assert "spreadsheetml" in res.headers["content-type"]
        assert c.get("/api/attachments/99999").status_code == 404


def test_unreadable_attachment_goes_to_a_person_even_if_the_model_says_other(shop):
    # Live eval, Nov 2026: Claude called the scanned-PDF email "other". The rule in
    # code doesn't depend on that call.
    ingest.run(shop, extract=lambda e: _ex("other") if e["id"] == "A03" else PERFECT[e["id"]])
    assert shop.execute("SELECT outcome FROM inbox_emails WHERE id = 'A03'").fetchone()[0] == "needs_review"


def test_unreadable_attachment_from_a_stranger_is_still_ignored(conn):
    email = {"id": "T3", "from_addr": "promo@unknown-vendor.example", "unreadable_attachments": [("x.pdf", "no text")]}
    assert normalize(conn, email, _ex("other")).ignored_reason
