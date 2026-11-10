"""Unit-of-measure conversion. Done in code, never by the LLM, in exact decimal arithmetic."""

from decimal import Decimal

from .money import D, cost

# The pound is defined as exactly 0.45359237 kg, so every factor here is exact.
_KG_PER_LB = Decimal("0.45359237")

LB_PER_UNIT: dict[str, Decimal] = {
    "lb": Decimal(1),
    "kg": 1 / _KG_PER_LB,
    "cwt": Decimal(100),              # US hundredweight
    "short_ton": Decimal(2000),
    "metric_ton": 1000 / _KG_PER_LB,
}


def to_cost_per_lb(price: float | Decimal, unit: str, pack_qty: float | Decimal | None = None,
                   *, in_cents: bool = False) -> Decimal:
    """Convert a quoted price to dollars per lb, rounded to 6 dp.

    `pack_qty` covers pack pricing, e.g. "$310 per 25 kg bag" is
    price=310, unit="kg", pack_qty=25. `in_cents` covers "118 cents per pound".
    """
    if unit not in LB_PER_UNIT:
        raise ValueError(f"unknown unit: {unit!r}")
    dollars = D(price) / 100 if in_cents else D(price)
    qty = D(pack_qty) if pack_qty and pack_qty > 0 else Decimal(1)
    return cost(dollars / (qty * LB_PER_UNIT[unit]))
