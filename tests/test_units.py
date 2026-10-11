import pytest

from margin_guard.units import to_cost_per_lb


def test_lb_passthrough():
    assert to_cost_per_lb(2.27, "lb") == pytest.approx(2.27)


def test_kg():
    assert to_cost_per_lb(5.20, "kg") == pytest.approx(2.35868, rel=1e-4)


def test_pack_of_25_kg():
    assert to_cost_per_lb(310.0, "kg", pack_qty=25) == pytest.approx(5.62455, rel=1e-4)


def test_cwt():
    assert to_cost_per_lb(118.0, "cwt") == pytest.approx(1.18)


def test_metric_ton():
    assert to_cost_per_lb(1980.0, "metric_ton") == pytest.approx(0.89811, rel=1e-4)


def test_zero_or_missing_pack_means_single_unit():
    assert to_cost_per_lb(2.0, "lb", pack_qty=0) == pytest.approx(2.0)
    assert to_cost_per_lb(2.0, "lb", pack_qty=None) == pytest.approx(2.0)


def test_unknown_unit_raises():
    with pytest.raises(ValueError):
        to_cost_per_lb(1.0, "gallon")
