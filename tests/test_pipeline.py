"""Normalization, event log and ingest, with no API calls.

PERFECT_EXTRACTIONS is what an ideal extractor would return for each inbox
email. Running it through the real pipeline must reproduce every gold outcome;
that pins down the deterministic half of the system, so the live eval measures
only Claude's extraction.
"""

import json

import pytest

from margin_guard import events, ingest
from margin_guard.parser import EmailExtraction, ExtractedChange, normalize


def _ch(text, price=None, unit=None, date=None, pack=None, old=None, pct=None):
    return ExtractedChange(material_text=text, new_price=price, price_unit=unit, pack_qty=pack,
                           old_price=old, pct_change=pct, effective_date=date)


def _ex(kind, changes=(), confidence=0.95):
    return EmailExtraction(email_kind=kind, changes=list(changes), confidence=confidence, rationale="test")


PERFECT_EXTRACTIONS = {
    "E01": _ex("price_change", [_ch("EPDM 70 duro compound", 2.27, "lb", "2026-11-01", old=2.10)]),
    "E02": _ex("price_change", [_ch("NBR 70 (Buna-N 70)", 5.20, "kg", "2026-11-15")]),
    "E03": _ex("price_change", [_ch("Silicone VMQ 50", 310.0, "kg", "2026-11-01", pack=25, old=281.10)]),
    "E04": _ex("price_change", [_ch("EPDM 70 duro compound", 2.27, "lb", "2026-11-01", old=2.10)]),
    "E05": _ex("price_change", [_ch("Neoprene 60 (CR 60)", 3.26, "lb", "2026-10-20", old=3.40)]),
    "E06": _ex("other"),
    "E07": _ex("price_change", [_ch("Black 70", 2.30, "lb", "2026-11-01")]),
    "E08": _ex("price_change", [_ch("FKM 75", None, None, "2026-12-01", pct=6.5)]),
    "E09": _ex("price_change", [_ch("N550 carbon black", 118.0, "cwt", "2026-11-01", old=109.0)]),
    "E10": _ex("price_change", [_ch("C1018 cold rolled bar", 1980.0, "metric_ton", "2026-11-01", old=1852.0)]),
    "E11": _ex("price_change", [_ch("NR 40 compound", None, None, "2027-02-01", pct=5.0)]),
    "E12": _ex("price_change", [_ch("EPDM 50 compound", 2.04, "lb", "2026-11-15", old=1.95),
                                _ch("SBR 60 compound", 1.70, "lb", "2026-11-15", old=1.62)]),
    "E13": _ex("price_change", [_ch("EPDM 60 compound", 2.05, "lb", "2026-10-01")]),
    "E14": _ex("supplier_offer"),
    "E15": _ex("price_advisory"),
}


def _email(conn, email_id):
    return conn.execute("SELECT * FROM inbox_emails WHERE id = ?", (email_id,)).fetchone()


def test_perfect_extractor_reproduces_gold_outcomes(conn, gold):
    outcomes = ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    assert outcomes == {i: g["gold"]["outcome"] for i, g in gold.items()}


def test_perfect_extractor_reproduces_gold_prices(conn, gold):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    for email_id, g in gold.items():
        if g["gold"]["outcome"] != "detected":
            continue
        got = {p["material_id"]: p for p in (
            json.loads(r["payload"]) for r in conn.execute(
                "SELECT payload FROM events WHERE source_ref = ? AND event_type = 'price_change.detected'",
                (f"email:{email_id}",)))}
        for change in g["gold"]["changes"]:
            p = got[change["material_id"]]
            assert p["new_cost_per_lb"] == pytest.approx(change["new_cost_per_lb"], rel=5e-4), email_id
            assert p["effective_date"] == change["effective_date"], email_id


def test_unit_error_trips_sanity_bound(conn):
    # NBR 70 at "$5.20/lb" (kg misread as lb) is a +131% move.
    ex = _ex("price_change", [_ch("NBR 70", 5.20, "lb", "2026-11-15")])
    result = normalize(conn, _email(conn, "E02"), ex)
    [draft] = result.drafts
    assert draft.event_type == "price_change.needs_review"
    assert any("sanity bound" in r for r in draft.payload["review_reasons"])


def test_low_confidence_goes_to_review(conn):
    ex = _ex("price_change", [_ch("EPDM 70", 2.27, "lb", "2026-11-01")], confidence=0.4)
    [draft] = normalize(conn, _email(conn, "E01"), ex).drafts
    assert draft.event_type == "price_change.needs_review"


def test_missing_date_goes_to_review(conn):
    ex = _ex("price_change", [_ch("EPDM 70", 2.27, "lb", None)])
    [draft] = normalize(conn, _email(conn, "E01"), ex).drafts
    assert "no effective date" in draft.payload["review_reasons"]


def test_price_notice_from_unknown_sender_is_ignored(conn):
    ex = _ex("price_change", [_ch("EPDM 70", 1.80, "lb", "2026-11-01")])
    result = normalize(conn, _email(conn, "E14"), ex)
    assert result.ignored_reason and not result.drafts


def test_event_append_is_idempotent(conn):
    draft = normalize(conn, _email(conn, "E01"), PERFECT_EXTRACTIONS["E01"]).drafts[0]
    first = events.append(conn, draft, "email:E01")
    second = events.append(conn, draft, "email:E04")
    assert first is not None and second is None
    assert len(events.pending(conn, "price_change.detected")) == 1


def test_already_applied_change_is_a_duplicate(conn):
    draft = normalize(conn, _email(conn, "E13"), PERFECT_EXTRACTIONS["E13"]).drafts[0]
    assert draft.event_type == "price_change.detected"
    assert events.append(conn, draft, "email:E13") is None


def test_extractor_failure_is_recorded_not_raised(conn):
    def boom(_):
        raise RuntimeError("api down")
    assert ingest.run(conn, email_id="E01", extract=boom) == {"E01": "error"}
    row = _email(conn, "E01")
    assert row["status"] == "error" and "api down" in row["error"]
