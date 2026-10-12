"""Which open quotes does a cost change hurt, and by how much? Pure code, no LLM.

Costs are cumulative: a quote's cost "after" uses every known material cost as of
the change's effective date, including earlier changes already logged. Two
changes that land on the same part therefore stack instead of being judged in
isolation.

Exposure assumes material for an order is bought when the order is placed, so a
quote that must be accepted before the change takes effect carries no exposure.
"""

import sqlite3


def cost_on(conn: sqlite3.Connection, material_id: str, on: str) -> float:
    """Material cost per lb in effect on a date, from the price history."""
    row = conn.execute(
        """SELECT cost_per_lb FROM material_price_history
           WHERE material_id = ? AND effective_date <= ?
           ORDER BY effective_date DESC, id DESC LIMIT 1""",
        (material_id, on),
    ).fetchone()
    if row:
        return row["cost_per_lb"]
    return conn.execute("SELECT cost_per_lb FROM materials WHERE id = ?", (material_id,)).fetchone()["cost_per_lb"]


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


def quote_facts(conn: sqlite3.Connection, quote_id: str, change: dict) -> dict:
    """Everything a decision about one quote needs, as plain data."""
    q = conn.execute(
        """SELECT q.*, c.name AS customer_name, c.tier, c.price_lock_until, c.contract_note
           FROM quotes q JOIN customers c ON c.id = q.customer_id WHERE q.id = ?""",
        (quote_id,),
    ).fetchone()
    effective = change["effective_date"]

    lines = []
    revenue = cost_before_total = cost_after_total = 0.0
    for ql in conn.execute(
        """SELECT ql.*, p.name AS part_name FROM quote_lines ql
           JOIN parts p ON p.id = ql.part_id WHERE ql.quote_id = ? ORDER BY ql.id""",
        (quote_id,),
    ):
        bom = conn.execute(
            "SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?", (ql["part_id"],)
        ).fetchall()
        material_after = sum(m["lb_per_unit"] * (1 + m["scrap_rate"]) * cost_on(conn, m["material_id"], effective)
                             for m in bom)
        unit_before = ql["material_cost_basis"] + ql["conversion_cost"]
        unit_after = material_after + ql["conversion_cost"]
        line_margin = 1 - unit_before / ql["unit_price"]
        # Restore the line's original margin on the new cost.
        proposed = round(unit_after / (1 - line_margin), 4) if unit_after > unit_before else ql["unit_price"]

        lines.append({
            "part_id": ql["part_id"],
            "part_name": ql["part_name"],
            "uses_changed_material": any(m["material_id"] == change["material_id"] for m in bom),
            "qty": ql["qty"],
            "unit_price": ql["unit_price"],
            "unit_cost_before": round(unit_before, 4),
            "unit_cost_after": round(unit_after, 4),
            "proposed_unit_price": proposed,
        })
        revenue += ql["qty"] * ql["unit_price"]
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
        "issued_date": q["issued_date"],
        "valid_until": q["valid_until"],
        "material_id": change["material_id"],
        "material_pct_change": change.get("pct_change"),
        "effective_date": effective,
        "quote_value_usd": round(revenue, 2),
        "margin_floor": q["margin_floor"],
        "margin_before": round(1 - cost_before_total / revenue, 4),
        "margin_after": round(1 - cost_after_total / revenue, 4),
        "can_accept_after_change": can_accept_after_change,
        "exposure_usd": round(cost_after_total - cost_before_total, 2) if can_accept_after_change else 0.0,
        "lines": lines,
    }


def affected_quotes(conn: sqlite3.Connection, change: dict) -> list[dict]:
    return [quote_facts(conn, qid, change) for qid in affected_quote_ids(conn, change["material_id"])]
