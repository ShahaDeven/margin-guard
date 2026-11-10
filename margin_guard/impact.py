"""Which open quotes does a cost change hurt, and by how much? Pure code, no LLM.

Costs are cumulative: a quote's cost "after" uses every known material cost as of
the change's effective date, including earlier changes already logged. Two
changes that land on the same part therefore stack instead of being judged in
isolation.

Exposure is replacement-cost exposure: it assumes material for an order is bought
when the order is placed, so a quote that must be accepted before the change takes
effect carries no exposure. Inventory already on hand is not modelled.

Costs come from each material's costing supplier only (catalog.costing_vendor).
History rows with no supplier are the shop's own cost entries and always count.
"""

import sqlite3

from . import catalog, money
from .money import ZERO, D, out


def moves_costing(conn: sqlite3.Connection, change: dict) -> bool:
    """Does this price change move the cost quotes are built on?

    True for the material's costing supplier, for a change with no supplier
    (entered by the shop), and for a material with no costing supplier marked.
    """
    costing = catalog.costing_vendor(conn, change["material_id"])
    vendor = change.get("vendor_id")
    return vendor is None or costing is None or vendor == costing


def supplier_cost(conn: sqlite3.Connection, material_id: str, vendor_id: str, on: str) -> float | None:
    """The latest price on file from one supplier, effective on or before a date."""
    row = conn.execute(
        """SELECT cost_per_lb FROM material_price_history
           WHERE material_id = ? AND vendor_id = ? AND effective_date <= ?
           ORDER BY effective_date DESC, id DESC LIMIT 1""",
        (material_id, vendor_id, on),
    ).fetchone()
    return row["cost_per_lb"] if row else None


Pending = dict | list[dict] | tuple[dict, ...] | None


def cost_entry(conn: sqlite3.Connection, material_id: str, on: str,
               pending: Pending = None) -> tuple[float, str | None]:
    """(cost per lb, date that cost took effect) for a material on a date,
    at the costing supplier's price.

    `pending` is one or more changes not yet written to history ({"material_id",
    "vendor_id", "new_cost_per_lb", "effective_date"}). They're treated as recorded,
    so impact can be computed without holding a write lock while the decision step
    runs. A pending change from an alternate supplier is ignored, like its history rows.
    """
    if isinstance(pending, (list, tuple)):
        best: tuple[float, str | None] | None = None
        for p in pending:
            entry = cost_entry(conn, material_id, on, p)
            if best is None or (entry[1] or "") >= (best[1] or ""):
                best = entry
        return best if best is not None else cost_entry(conn, material_id, on)
    costing = catalog.costing_vendor(conn, material_id)
    row = conn.execute(
        """SELECT cost_per_lb, effective_date FROM material_price_history
           WHERE material_id = ? AND effective_date <= ?
             AND (vendor_id IS NULL OR ? IS NULL OR vendor_id = ?)
           ORDER BY effective_date DESC, id DESC LIMIT 1""",
        (material_id, on, costing, costing),
    ).fetchone()
    if (pending and pending.get("new_cost_per_lb") is not None and pending["material_id"] == material_id
            and moves_costing(conn, pending)
            and pending["effective_date"] <= on and (row is None or pending["effective_date"] >= row["effective_date"])):
        return pending["new_cost_per_lb"], pending["effective_date"]
    if row:
        return row["cost_per_lb"], row["effective_date"]
    cost = conn.execute("SELECT cost_per_lb FROM materials WHERE id = ?", (material_id,)).fetchone()["cost_per_lb"]
    return cost, None


def cost_on(conn: sqlite3.Connection, material_id: str, on: str, pending: Pending = None) -> float:
    """Material cost per lb in effect on a date, from the price history."""
    return cost_entry(conn, material_id, on, pending)[0]


def affected_quote_ids(conn: sqlite3.Connection, material_id: str) -> list[str]:
    rows = conn.execute(
        """SELECT DISTINCT q.id FROM quotes q
           JOIN quote_lines ql ON ql.quote_id = q.id
           JOIN part_materials pm ON pm.part_id = ql.part_id
           WHERE q.status = 'open' AND pm.material_id = ?
           ORDER BY q.id""",
        (material_id,),
    )
    return [r["id"] for r in rows]


def quote_facts(conn: sqlite3.Connection, quote_id: str, change: dict, also: tuple[dict, ...] = ()) -> dict:
    """Everything a decision about one quote needs, as plain data.

    `also` are further changes not yet recorded that the costs should include,
    e.g. an earlier-dated change that arrived after this card was first made.
    """
    pending = (change, *also)
    q = conn.execute(
        """SELECT q.*, c.name AS customer_name, c.tier, c.price_lock_until, c.contract_note,
                  c.buyer_name, c.buyer_phone, c.buyer_email, c.account_manager, c.account_manager_phone
           FROM quotes q JOIN customers c ON c.id = q.customer_id WHERE q.id = ?""",
        (quote_id,),
    ).fetchone()
    effective = change["effective_date"]

    # Every material cost that moved between quoting and the effective date. With
    # stacking, a card can cover more than the change that triggered it, and the
    # person (and Claude) must see all of them.
    moved: dict[str, dict] = {}

    def track(material_id: str) -> None:
        if material_id in moved:
            return
        then, _ = cost_entry(conn, material_id, q["issued_date"])
        now, since = cost_entry(conn, material_id, effective, pending)
        name = conn.execute("SELECT name FROM materials WHERE id = ?", (material_id,)).fetchone()["name"]
        moved[material_id] = {"material_id": material_id, "material_name": name,
                              "cost_when_quoted": then, "cost_after": now,
                              "pct_change": out(money.pct((D(now) - D(then)) / D(then))), "effective_date": since,
                              "changed": D(now) != D(then)}

    # All arithmetic below is Decimal (see money.py); values become floats only
    # when they go into the facts, already rounded to their precision.
    lines = []
    revenue = cost_before_total = cost_after_total = ZERO
    for ql in conn.execute(
        """SELECT ql.*, p.name AS part_name FROM quote_lines ql
           JOIN parts p ON p.id = ql.part_id WHERE ql.quote_id = ? ORDER BY ql.id""",
        (quote_id,),
    ):
        bom = conn.execute(
            "SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?", (ql["part_id"],)
        ).fetchall()
        material_after = sum(
            (D(m["lb_per_unit"]) * (1 + D(m["scrap_rate"])) * D(cost_on(conn, m["material_id"], effective, pending))
             for m in bom), ZERO)
        unit_price = D(ql["unit_price"])
        unit_before = D(ql["material_cost_basis"]) + D(ql["conversion_cost"])
        unit_after = material_after + D(ql["conversion_cost"])
        # Restore the line's original margin on the new cost. With margin
        # m = 1 - before/price, after/(1 - m) is after * price / before; this
        # form never rounds through the margin.
        proposed = money.price(unit_after * unit_price / unit_before) if unit_after > unit_before else unit_price
        for m in bom:
            track(m["material_id"])

        lines.append({
            "line_id": ql["id"],
            "part_id": ql["part_id"],
            "part_name": ql["part_name"],
            "uses_changed_material": any(m["material_id"] == change["material_id"] for m in bom),
            "changed_materials": [m["material_id"] for m in bom if moved[m["material_id"]]["changed"]],
            "qty": ql["qty"],
            "unit_price": out(unit_price),
            "unit_cost_before": out(money.price(unit_before)),
            "unit_cost_after": out(money.price(unit_after)),
            "proposed_unit_price": out(proposed),
        })
        revenue += ql["qty"] * unit_price
        cost_before_total += ql["qty"] * unit_before
        cost_after_total += ql["qty"] * unit_after

    can_accept_after_change = q["valid_until"] >= effective
    return {
        "quote_id": quote_id,
        "customer_id": q["customer_id"],
        "customer_name": q["customer_name"],
        "customer_tier": q["tier"],
        "price_lock_until": q["price_lock_until"],
        "contract_note": q["contract_note"],
        "buyer": {"name": q["buyer_name"], "phone": q["buyer_phone"], "email": q["buyer_email"]},
        "account_manager": {"name": q["account_manager"], "phone": q["account_manager_phone"]},
        "issued_date": q["issued_date"],
        "valid_until": q["valid_until"],
        "material_id": change["material_id"],
        "material_pct_change": change.get("pct_change"),
        "effective_date": effective,
        "quote_value_usd": out(money.cents(revenue)),
        "margin_floor": q["margin_floor"],
        "margin_before": out(money.ratio(1 - cost_before_total / revenue)),
        "margin_after": out(money.ratio(1 - cost_after_total / revenue)),
        "can_accept_after_change": can_accept_after_change,
        "exposure_usd": out(money.cents(cost_after_total - cost_before_total)) if can_accept_after_change else 0.0,
        # Trigger first, then the rest by date.
        "cost_changes": sorted(
            ({k: v for k, v in c.items() if k != "changed"} for c in moved.values() if c["changed"]),
            key=lambda c: (c["material_id"] != change["material_id"], c["effective_date"] or ""),
        ),
        "lines": lines,
    }


def affected_quotes(conn: sqlite3.Connection, change: dict) -> list[dict]:
    return [quote_facts(conn, qid, change) for qid in affected_quote_ids(conn, change["material_id"])]
