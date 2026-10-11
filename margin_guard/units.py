"""Unit-of-measure conversion. Done in code, never by the LLM."""

LB_PER_UNIT = {
    "lb": 1.0,
    "kg": 2.20462262,
    "cwt": 100.0,              # US hundredweight
    "short_ton": 2000.0,
    "metric_ton": 2204.62262,
}


def to_cost_per_lb(price: float, unit: str, pack_qty: float | None = None) -> float:
    """Convert a quoted price to cost per lb.

    `pack_qty` covers pack pricing, e.g. "$310 per 25 kg bag" is
    price=310, unit="kg", pack_qty=25.
    """
    if unit not in LB_PER_UNIT:
        raise ValueError(f"unknown unit: {unit!r}")
    qty = pack_qty if pack_qty and pack_qty > 0 else 1.0
    return price / (qty * LB_PER_UNIT[unit])
