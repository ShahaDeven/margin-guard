"""Quote check: increases on file that land inside a new quote's validity, and the ways out."""

import json

import pytest

from margin_guard import quotecheck
from margin_guard.money import D


@pytest.fixture
def shop(conn):
    # Two increases on file for Nov 1, as the inbox would leave them (costing suppliers).
    conn.executemany("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                     " VALUES (?, ?, ?, ?)",
                     [("MAT-EPDM-70", "V-MWP", 2.27, "2026-11-01"), ("MAT-CB-N550", "V-RCB", 1.18, "2026-11-01")])
    return conn


def _customer(conn, lock=None):
    cid = conn.execute("SELECT id FROM customers WHERE price_lock_until IS NULL ORDER BY id LIMIT 1").fetchone()[0]
    if lock:
        conn.execute("UPDATE customers SET price_lock_until = ? WHERE id = ?", (lock, cid))
    return cid


def _check(conn, *, days=60, floor=0.28, price=6.6519, part="P-1004", qty=2500, customer=None):
    return quotecheck.check(conn, customer_id=customer or _customer(conn), valid_days=days, margin_floor=floor,
                            lines=[{"part_id": part, "qty": qty, "unit_price": price}])


def test_increase_inside_the_window_is_caught(shop):
    r = _check(shop)
    assert r["verdict"] == "below_floor_after_change"
    assert [t["date"] for t in r["timeline"]] == ["2026-10-15", "2026-11-01"]
    assert {c["material_id"] for c in r["changes"]} == {"MAT-EPDM-70", "MAT-CB-N550"}
    # P-1004: 1.10 lb EPDM 70 at 5% scrap + 0.12 lb N550 + $2.10 conversion.
    before = D("1.10") * D("1.05") * D("2.10") + D("0.12") * D("1.09") + D("2.10")
    after = D("1.10") * D("1.05") * D("2.27") + D("0.12") * D("1.18") + D("2.10")
    assert r["lines"][0]["unit_cost_now"] == pytest.approx(float(before), abs=1e-4)
    assert r["lines"][0]["unit_cost_at_expiry"] == pytest.approx(float(after), abs=1e-4)
    assert r["at_risk_usd"] == pytest.approx(float(2500 * (after - before)), abs=0.01)
    assert r["lines"][0]["price_to_hold_margin"] == pytest.approx(float(after * D("6.6519") / before), abs=1e-4)


def test_verdicts(shop):
    assert _check(shop, days=10)["verdict"] == "clear"                      # expires Oct 25
    assert _check(shop, floor=0.20)["verdict"] == "margin_erodes"           # 30% -> 26.9%, floor 20%
    assert _check(shop, price=5.0)["verdict"] == "below_floor_now"


def test_shorten_suggestion_clears_the_window(shop):
    r = _check(shop)
    shorten = next(s for s in r["suggestions"] if s["kind"] == "shorten")
    assert shorten["valid_until"] == "2026-10-31" and shorten["valid_days"] == 16
    assert "Oct 31, 2026" in shorten["text"]
    assert _check(shop, days=shorten["valid_days"])["verdict"] == "clear"


def test_reprice_suggestion_holds_the_margin(shop):
    r = _check(shop)
    held = next(s for s in r["suggestions"] if s["kind"] == "reprice")["value_usd"]
    again = _check(shop, price=r["lines"][0]["price_to_hold_margin"])
    assert held == pytest.approx(again["value_usd"], abs=0.01)
    assert again["margin_at_expiry"] == pytest.approx(r["margin_now"], abs=2e-4)


def test_clause_names_each_material_and_its_announced_price(shop):
    clause = next(s for s in _check(shop)["suggestions"] if s["kind"] == "clause")["text"]
    assert "$2.10/lb" in clause and "$2.27/lb from Nov 1, 2026" in clause and "$1.18/lb" in clause


def test_alternate_supplier_prices_are_not_increases(conn):
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-EPDM-70', 'V-KRD', 2.60, '2026-11-01')")
    assert _check(conn)["verdict"] == "clear"


def test_price_lock_only_flags_when_it_covers_an_increase(shop):
    assert _check(shop, customer=_customer(shop, lock="2026-11-10"))["price_locked"]
    shop.execute("UPDATE customers SET price_lock_until = '2026-10-20' WHERE price_lock_until = '2026-11-10'")
    cid = shop.execute("SELECT id FROM customers WHERE price_lock_until = '2026-10-20'").fetchone()[0]
    assert not _check(shop, customer=cid)["price_locked"]


def test_waiting_supplier_email_is_flagged(shop):
    ev = shop.execute("INSERT INTO events (event_type, idempotency_key, payload) VALUES"
                      " ('price_change.needs_review', 'k-qc', '{}')").lastrowid
    shop.execute("INSERT INTO proposals (idempotency_key, event_id, kind, action, decided_by, rationale, facts)"
                 " VALUES ('qc', ?, 'event_review', 'resolve_event', 'rule', 'r', ?)",
                 (ev, json.dumps({"email_id": "E07", "match_candidates": ["MAT-EPDM-70", "MAT-NBR-70"],
                                  "review_reasons": ["ambiguous"]})))
    [p] = _check(shop)["pending_reviews"]
    assert p["email_id"] == "E07" and p["materials"] == ["MAT-EPDM-70"]


def test_bad_input_is_refused(shop):
    with pytest.raises(quotecheck.CheckError, match="unknown part"):
        _check(shop, part="P-NOPE")
    with pytest.raises(quotecheck.CheckError, match="more than 0"):
        _check(shop, qty=0)


def test_api(shop, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", shop)
    with TestClient(api.app) as c:
        parts = c.get("/api/parts").json()
        assert any(p["id"] == "P-1004" and p["unit_cost_now"] > 0 for p in parts)
        body = {"customer_id": _customer(shop), "valid_days": 60, "margin_floor": 0.28,
                "lines": [{"part_id": "P-1004", "qty": 2500, "unit_price": 6.6519}]}
        assert c.post("/api/quote-check", json=body).json()["verdict"] == "below_floor_after_change"
        bad = c.post("/api/quote-check", json={**body, "lines": [{"part_id": "P-NOPE", "qty": 1, "unit_price": 1}]})
        assert bad.status_code == 400
