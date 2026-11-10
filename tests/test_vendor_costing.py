"""Supplier-specific costing: quotes are costed at one supplier's price per material.

EPDM 70 is bought from Midwest Polymer (costing supplier) and Keystone Rubber
(alternate). A Keystone price is recorded but must not move any quote's margin.
"""

import json

import pytest
from test_pipeline import _ch, _ex

from margin_guard import catalog, coordinator, events, impact
from margin_guard.parser import normalize

MIDWEST = {"id": "T-MWP", "from_addr": "pricing@midwestpolymer.com"}
KEYSTONE = {"id": "T-KRD", "from_addr": "sales@keystonerubber.com"}


def NO_DECIDER(facts):
    raise AssertionError(f"no quote should reach a decision ({facts['quote_id']})")


def _append(conn, email, extraction):
    [draft] = normalize(conn, email, extraction).drafts
    return draft, events.append(conn, draft, source_ref=f"email:{email['id']}")


def _history(conn, vendor_id, cost, effective):
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-EPDM-70', ?, ?, ?)", (vendor_id, cost, effective))


def test_costing_supplier_is_the_primary_one(conn):
    assert catalog.costing_vendor(conn, "MAT-EPDM-70") == "V-MWP"
    assert catalog.costing_vendor(conn, "MAT-NBR-70") == "V-GLE"


def test_alternate_supplier_price_is_recorded_but_creates_no_cards(conn):
    # The holdout's H05: Keystone passes through an EPDM 70 increase.
    draft, event_id = _append(conn, KEYSTONE, _ex("price_change", [_ch("EPDM 70", 2.34, "lb", "2026-11-15")]))
    assert draft.event_type == "price_change.detected" and event_id is not None

    coordinator.run(conn, NO_DECIDER)
    assert conn.execute("SELECT COUNT(*) FROM proposals WHERE event_id = ?", (event_id,)).fetchone()[0] == 0
    result = json.loads(conn.execute("SELECT result FROM events WHERE id = ?", (event_id,)).fetchone()[0])
    assert result["alt_supplier"] and result["costing_cost_per_lb"] == pytest.approx(2.10)
    assert "Keystone" in result["note"] and "Midwest" in result["note"]
    assert conn.execute("SELECT vendor_id, cost_per_lb FROM material_price_history WHERE source_event_id = ?",
                        (event_id,)).fetchone()[:] == ("V-KRD", 2.34)


def test_alternate_supplier_price_does_not_change_the_catalog_cost(conn):
    _, event_id = _append(conn, KEYSTONE, _ex("price_change", [_ch("EPDM 70", 1.95, "lb", "2026-10-01")]))
    coordinator.run(conn, NO_DECIDER)
    assert conn.execute("SELECT cost_per_lb FROM materials WHERE id = 'MAT-EPDM-70'").fetchone()[0] == 2.10


def test_alternate_supplier_history_is_ignored_by_impact(conn):
    _history(conn, "V-KRD", 2.60, "2026-11-01")
    assert impact.cost_on(conn, "MAT-EPDM-70", "2026-12-01") == pytest.approx(2.10)
    # A shop-entered cost (no supplier) still counts.
    _history(conn, None, 2.20, "2026-11-10")
    assert impact.cost_on(conn, "MAT-EPDM-70", "2026-12-01") == pytest.approx(2.20)


def test_pending_alternate_change_is_ignored_by_impact(conn):
    pending = {"material_id": "MAT-EPDM-70", "vendor_id": "V-KRD", "new_cost_per_lb": 2.60,
               "effective_date": "2026-11-01"}
    assert impact.cost_on(conn, "MAT-EPDM-70", "2026-12-01", pending) == pytest.approx(2.10)
    assert impact.cost_on(conn, "MAT-EPDM-70", "2026-12-01", pending | {"vendor_id": "V-MWP"}) == pytest.approx(2.60)


def test_costing_supplier_change_still_creates_cards(conn):
    _, event_id = _append(conn, MIDWEST, _ex("price_change", [_ch("EPDM 70", 2.27, "lb", "2026-11-01")]))
    coordinator.run(conn, lambda f: (_ for _ in ()).throw(RuntimeError("escalate")))
    n = conn.execute("SELECT COUNT(*) FROM proposals WHERE event_id = ?", (event_id,)).fetchone()[0]
    assert n == len(impact.affected_quote_ids(conn, "MAT-EPDM-70")) > 0


def test_two_suppliers_same_price_same_date_are_two_changes(conn):
    ex = _ex("price_change", [_ch("EPDM 70", 2.30, "lb", "2026-11-01")])
    mwp_draft, mwp_id = _append(conn, MIDWEST, ex)
    krd_draft, krd_id = _append(conn, KEYSTONE, ex)
    assert mwp_draft.idempotency_key != krd_draft.idempotency_key
    assert mwp_id is not None and krd_id is not None


def test_same_supplier_resend_is_still_a_duplicate(conn):
    ex = _ex("price_change", [_ch("EPDM 70", 2.30, "lb", "2026-11-01")])
    _append(conn, MIDWEST, ex)
    _, again = _append(conn, {**MIDWEST, "from_addr": "accounts@midwestpolymer.com"}, ex)
    assert again is None


def test_pct_change_applies_to_the_senders_own_price(conn):
    _history(conn, "V-KRD", 2.40, "2026-09-01")
    draft, _ = _append(conn, KEYSTONE, _ex("price_change", [_ch("EPDM 70", pct=5.0, date="2026-12-01")]))
    assert draft.event_type == "price_change.detected"
    assert draft.payload["new_cost_per_lb"] == pytest.approx(2.40 * 1.05)
    assert draft.payload["old_cost_per_lb"] == pytest.approx(2.40)


def test_pct_change_from_alternate_supplier_without_a_price_goes_to_a_person(conn):
    draft, _ = _append(conn, KEYSTONE, _ex("price_change", [_ch("EPDM 70", pct=5.0, date="2026-12-01")]))
    assert draft.event_type == "price_change.needs_review"
    assert any("alternate supplier" in r for r in draft.payload["review_reasons"])


def test_pct_change_from_costing_supplier_uses_catalog_cost(conn):
    draft, _ = _append(conn, MIDWEST, _ex("price_change", [_ch("EPDM 70", pct=5.0, date="2026-12-01")]))
    assert draft.payload["new_cost_per_lb"] == pytest.approx(2.10 * 1.05)
