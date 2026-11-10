"""Money arithmetic: every figure is computed in Decimal and rounded once, deliberately.

Floats exist only at the edges: SQLite REAL columns and JSON. A value is
rounded to its precision before it is stored, and `D()` reads it back through
its shortest repr, which recovers the decimal exactly (anything up to 15
significant digits survives a round trip through a double; a 6-dp cost up to
$10M is 14). So storage never adds error, and arithmetic never sees binary
noise: in float, ten $0.10 lines sum to $0.9999999999999999.

Rounding is ROUND_HALF_UP, the commercial convention. Python's round() rounds
the binary value instead: round(2.675, 2) == 2.67.

Precision by kind of number:
    COST    material cost per lb           6 dp
    PRICE   unit prices and unit costs     4 dp
    CENTS   quote totals, exposure, $      2 dp
    RATIO   margins                        4 dp (0.01 percentage point)
    PCT     % change as a fraction         6 dp
"""

from decimal import ROUND_HALF_UP, Decimal

COST = Decimal("0.000001")
PRICE = Decimal("0.0001")
CENTS = Decimal("0.01")
RATIO = Decimal("0.0001")
PCT = Decimal("0.000001")

ZERO = Decimal(0)


def D(x: Decimal | float | int | str) -> Decimal:
    """Any number as a Decimal. Floats go through repr, never Decimal(float),
    which would carry the binary expansion (Decimal(2.1) = 2.100000000000000088...)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool) or x is None:
        raise TypeError(f"not a number: {x!r}")
    if isinstance(x, float):
        return Decimal(repr(x))
    return Decimal(x)


def q(x: Decimal | float | int | str, step: Decimal) -> Decimal:
    return D(x).quantize(step, rounding=ROUND_HALF_UP)


def cost(x) -> Decimal:
    return q(x, COST)


def price(x) -> Decimal:
    return q(x, PRICE)


def cents(x) -> Decimal:
    return q(x, CENTS)


def ratio(x) -> Decimal:
    return q(x, RATIO)


def pct(x) -> Decimal:
    return q(x, PCT)


def out(x: Decimal) -> float:
    """A rounded Decimal as a float for JSON or a REAL column. Exact by the
    argument above, so float(out(x)) read back with D() is x again."""
    return float(x)
