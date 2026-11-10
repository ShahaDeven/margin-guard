"""Money precision: Decimal arithmetic, half-up rounding, exact REAL storage,
cents and currency in supplier emails, and impact numbers that add up."""

import json
import random
import sqlite3
from decimal import Decimal

import pytest
from test_pipeline import _ch, _ex

from margin_guard import impact, money
from margin_guard.money import D
from margin_guard.parser import normalize

RIDGELINE = {"id": "T-RCB", "from_addr": "customerservice@ridgelinecarbon.com"}
FLUOROTECH = {"id": "T-FLT", "from_addr": "commercial@fluorotechmaterials.com"}


# ------------------------------------------------------------------ money.py


def test_floats_enter_through_repr_not_binary():
    assert D(2.1) == Decimal("2.1")
    assert D(0.1) + D(0.2) == Decimal("0.3")


def test_rounding_is_half_up():
    assert round(2.675, 2) == 2.67              # what float round() does
    assert money.cents(2.675) == Decimal("2.68")
    assert money.price("1.00005") == Decimal("1.0001")


def test_sums_do_not_drift():
    assert sum([0.1] * 10) != 1.0
    assert sum((D(0.1) for _ in range(10)), money.ZERO) == 1


def test_rounded_values_survive_real_storage_exactly():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (x REAL)")
    rng = random.Random(7)
    for _ in range(5000):
        v = D(rng.randint(0, 10**13)) / D(10**6)          # 6 dp, up to $10M
        conn.execute("DELETE FROM t")
        conn.execute("INSERT INTO t VALUES (?)", (money.out(v),))
        assert D(conn.execute("SELECT x FROM t").fetchone()[0]) == v


def test_bool_and_none_are_not_numbers():
    with pytest.raises(TypeError):
        D(None)
    with pytest.raises(TypeError):
        D(True)


# ------------------------------------------------------------------ cents and currency


def test_price_in_cents_is_converted(conn):
    # The holdout's H07: "118 cents per pound" used to be read as $118/lb.
    ex = _ex("price_change", [_ch("N550", 118, "lb", "2027-01-01").model_copy(update={"price_in_cents": True})])
    [draft] = normalize(conn, RIDGELINE, ex).drafts
    assert draft.event_type == "price_change.detected"
    assert draft.payload["new_cost_per_lb"] == 1.18
    assert draft.payload["quoted"]["in_cents"] is True


def test_cents_read_as_dollars_still_trips_the_sanity_bound(conn):
    ex = _ex("price_change", [_ch("N550", 118, "lb", "2027-01-01")])
    [draft] = normalize(conn, RIDGELINE, ex).drafts
    assert draft.event_type == "price_change.needs_review"


def test_foreign_currency_goes_to_a_person(conn):
    ex = _ex("price_change", [_ch("FKM 75", 21.40, "lb", "2026-12-01").model_copy(update={"currency": "cad"})])
    [draft] = normalize(conn, FLUOROTECH, ex).drafts
    assert draft.event_type == "price_change.needs_review"
    assert any("CAD" in r for r in draft.payload["review_reasons"])


def test_old_cached_extractions_still_validate():
    from margin_guard.parser import ExtractedChange
    ch = ExtractedChange.model_validate({"material_text": "N550", "new_price": 1.2, "price_unit": "lb",
                                         "pack_qty": None, "old_price": None, "pct_change": None,
                                         "effective_date": "2027-01-01"})
    assert ch.price_in_cents is False and ch.currency == "USD"


# ------------------------------------------------------------------ impact


@pytest.fixture
def epdm_facts(conn):
    change = {"material_id": "MAT-EPDM-70", "vendor_id": "V-MWP", "new_cost_per_lb": 2.27,
              "effective_date": "2026-11-01", "pct_change": 0.080952}
    return impact.affected_quotes(conn, change)


def test_facts_are_plain_json(epdm_facts):
    assert epdm_facts
    json.dumps(epdm_facts)                        # no Decimal leaks into facts


def test_every_figure_is_rounded_to_its_precision(epdm_facts):
    for f in epdm_facts:
        assert D(f["exposure_usd"]) == money.cents(f["exposure_usd"])
        assert D(f["quote_value_usd"]) == money.cents(f["quote_value_usd"])
        assert D(f["margin_after"]) == money.ratio(f["margin_after"])
        for ln in f["lines"]:
            assert D(ln["proposed_unit_price"]) == money.price(ln["proposed_unit_price"])


def test_revised_price_restores_each_lines_margin(epdm_facts):
    for f in epdm_facts:
        for ln in f["lines"]:
            if ln["proposed_unit_price"] == ln["unit_price"]:
                continue
            before = 1 - D(ln["unit_cost_before"]) / D(ln["unit_price"])
            after = 1 - D(ln["unit_cost_after"]) / D(ln["proposed_unit_price"])
            # Off by at most the 4-dp rounding of the price (and of the shown costs).
            assert abs(after - before) < Decimal("0.0002"), (f["quote_id"], ln["line_id"])


def test_exposure_is_the_added_cost_to_the_cent(epdm_facts):
    for f in epdm_facts:
        if not f["can_accept_after_change"]:
            assert f["exposure_usd"] == 0.0
            continue
        added = sum((ln["qty"] * (D(ln["unit_cost_after"]) - D(ln["unit_cost_before"])) for ln in f["lines"]),
                    money.ZERO)
        # Line costs in the facts are rounded to 4 dp, so allow that much per unit.
        slack = sum(ln["qty"] for ln in f["lines"]) * Decimal("0.0001")
        assert abs(D(f["exposure_usd"]) - added) <= slack + Decimal("0.01"), f["quote_id"]
