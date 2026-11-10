from decimal import Decimal

import pytest

from margin_guard.units import LB_PER_UNIT, to_cost_per_lb

# Conversions are exact Decimal arithmetic rounded to 6 dp, so they are compared
# exactly, not approximately.


def test_lb_passthrough():
    assert to_cost_per_lb(2.27, "lb") == Decimal("2.270000")


def test_kg():
    # 1 lb = 0.45359237 kg exactly, so $/kg * 0.45359237 = $/lb.
    assert to_cost_per_lb(5.20, "kg") == Decimal("2.358680")


def test_pack_of_25_kg():
    assert to_cost_per_lb(310.0, "kg", pack_qty=25) == Decimal("5.624545")


def test_pack_in_lb():
    assert to_cost_per_lb(57.25, "lb", pack_qty=50) == Decimal("1.145000")


def test_cwt():
    assert to_cost_per_lb(118.0, "cwt") == Decimal("1.180000")


def test_metric_ton():
    assert to_cost_per_lb(1980.0, "metric_ton") == Decimal("0.898113")


def test_cents():
    assert to_cost_per_lb(118, "lb", in_cents=True) == Decimal("1.180000")
    assert to_cost_per_lb(88.5, "lb", in_cents=True) == Decimal("0.885000")
    assert to_cost_per_lb(5620, "metric_ton", in_cents=True) == to_cost_per_lb(56.20, "metric_ton")


def test_factors_are_exact():
    assert LB_PER_UNIT["kg"] * Decimal("0.45359237") == pytest.approx(Decimal(1), abs=Decimal("1e-25"))
    assert LB_PER_UNIT["metric_ton"] == pytest.approx(1000 * LB_PER_UNIT["kg"], abs=Decimal("1e-22"))


def test_zero_or_missing_pack_means_single_unit():
    assert to_cost_per_lb(2.0, "lb", pack_qty=0) == Decimal("2.000000")
    assert to_cost_per_lb(2.0, "lb", pack_qty=None) == Decimal("2.000000")


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        to_cost_per_lb(1.0, "gallon")
