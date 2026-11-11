"""Check a quote before it goes out: will a price change already on file land inside it?

Margin Guard's queue repairs open quotes after a supplier raises a price. The
cheaper fix is at quote time: if an increase on file takes effect while the new
quote is still valid, the customer can accept after it and the job ships at the
old price on the new cost. This check works it out before the quote is sent:

    the cost and margin today, at the quoted prices
    every increase on file (costing supplier, dated after today) that lands
    before the quote expires, and the margin if the order comes after it
    three ways out: a validity that ends before the first increase, prices that
    hold the margin through every increase, and an escalation clause
    flags: a customer price lock (an escalation clause may not hold), and supplier
    emails about these materials still waiting for a person

All arithmetic is code (Decimal, money.py) on the same price history as impact.py.
Nothing is saved; quotes live in the shop's quoting system.
"""

import json
import sqlite3
from datetime import date, timedelta

from . import catalog, impact, money
from .money import ZERO, D, out


class CheckError(ValueError):
    pass


def _day(iso: str) -> str:
    """'2026-10-31' as 'Oct 31, 2026' for the sentences a person reads."""
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def _changes(conn: sqlite3.Connection, material_ids: set[str], after: str, until: str) -> list[dict]:
    """Costing-supplier price changes on file, effective after `after` and on or before `until`."""
    out_rows = []
    for m in sorted(material_ids):
        costing = catalog.costing_vendor(conn, m)
        for r in conn.execute(
            """SELECT h.id, h.effective_date, h.cost_per_lb, v.name AS vendor_name,
                      json_extract(e.payload, '$.email_id') AS email_id
               FROM material_price_history h
               LEFT JOIN vendors v ON v.id = h.vendor_id
               LEFT JOIN events e ON e.id = h.source_event_id
               WHERE h.material_id = ? AND h.effective_date > ? AND h.effective_date <= ?
                 AND (h.vendor_id IS NULL OR ? IS NULL OR h.vendor_id = ?)
               ORDER BY h.effective_date, h.id""",
            (m, after, until, costing, costing),
        ):
            out_rows.append({"material_id": m, **dict(r)})
    return sorted(out_rows, key=lambda r: (r["effective_date"], r["material_id"]))


def check(conn: sqlite3.Connection, *, customer_id: str, lines: list[dict], valid_days: int,
          margin_floor: float, issued: str | None = None) -> dict:
    """`lines`: [{"part_id", "qty", "unit_price"}]. Returns the check as plain data."""
    from .config import AS_OF

    issued = issued or AS_OF.isoformat()
    if not lines:
        raise CheckError("add at least one line")
    if valid_days < 1:
        raise CheckError("validity must be at least a day")
    if not 0 <= margin_floor < 1:
        raise CheckError("margin floor is a fraction from 0 to 1")
    cust = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if cust is None:
        raise CheckError(f"unknown customer {customer_id}")
    valid_until = (date.fromisoformat(issued) + timedelta(days=valid_days)).isoformat()

    parts = {}
    for ln in lines:
        p = conn.execute("SELECT * FROM parts WHERE id = ?", (ln["part_id"],)).fetchone()
        if p is None:
            raise CheckError(f"unknown part {ln['part_id']}")
        if ln["qty"] <= 0 or ln["unit_price"] <= 0:
            raise CheckError(f"{ln['part_id']}: quantity and price must be more than 0")
        parts[ln["part_id"]] = (p, conn.execute(
            "SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?", (ln["part_id"],)).fetchall())

    materials = {m["material_id"] for _, bom in parts.values() for m in bom}
    changes = _changes(conn, materials, issued, valid_until)
    names = dict(conn.execute("SELECT id, name FROM materials").fetchall())
    # The dates the quote's cost can step: today, then each increase on file inside the window.
    dates = [issued] + sorted({c["effective_date"] for c in changes})

    def unit_cost(part_id: str, on: str) -> money.Decimal:
        p, bom = parts[part_id]
        material = sum((D(m["lb_per_unit"]) * (1 + D(m["scrap_rate"])) * D(impact.cost_on(conn, m["material_id"], on))
                        for m in bom), ZERO)
        return material + D(p["conversion_cost"])

    revenue = sum((D(ln["qty"]) * D(ln["unit_price"]) for ln in lines), ZERO)
    floor = D(margin_floor)
    timeline = []
    for d in dates:
        cost = sum((D(ln["qty"]) * unit_cost(ln["part_id"], d) for ln in lines), ZERO)
        timeline.append({"date": d, "cost_usd": out(money.cents(cost)),
                         "margin": out(money.ratio(1 - cost / revenue)),
                         "below_floor": (1 - cost / revenue) < floor,
                         "changes": [c for c in changes if c["effective_date"] == d]})
    now, worst = timeline[0], timeline[-1]

    out_lines = []
    for ln in lines:
        p, bom = parts[ln["part_id"]]
        before, after = unit_cost(ln["part_id"], issued), unit_cost(ln["part_id"], valid_until)
        price = D(ln["unit_price"])
        margin_now = 1 - before / price
        # Price that keeps this line's margin once every increase in the window has landed
        # (same form as impact.py: after * price / before).
        hold = money.price(after * price / before) if after > before else price
        out_lines.append({
            "part_id": ln["part_id"], "part_name": p["name"], "qty": ln["qty"], "unit_price": out(money.price(price)),
            "unit_cost_now": out(money.price(before)), "unit_cost_at_expiry": out(money.price(after)),
            "margin_now": out(money.ratio(margin_now)), "margin_at_expiry": out(money.ratio(1 - after / price)),
            "price_to_hold_margin": out(hold),
            "materials": [m["material_id"] for m in bom],
            "affected": any(c["material_id"] in {m["material_id"] for m in bom} for c in changes),
        })

    first = dates[1] if len(dates) > 1 else None
    lock = cust["price_lock_until"]
    # A lock only matters if it still holds when an increase lands: then an escalation
    # clause can't move the price.
    locked = bool(lock and first and lock >= first)
    pending = []
    for r in conn.execute(
        """SELECT p.id, p.facts FROM proposals p WHERE p.kind = 'event_review' AND p.status = 'pending'"""):
        f = json.loads(r["facts"])
        hit = materials & set(f.get("match_candidates") or []) | (materials & {f.get("material_id")})
        if hit:
            pending.append({"proposal_id": r["id"], "email_id": f.get("email_id"), "kind": f.get("kind"),
                            "materials": sorted(hit), "reasons": f.get("review_reasons", [])})

    suggestions = []
    if changes:
        safe_until = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
        safe_days = (date.fromisoformat(safe_until) - date.fromisoformat(issued)).days
        if safe_days >= 1:
            suggestions.append({"kind": "shorten", "valid_until": safe_until, "valid_days": safe_days,
                                "text": f"Make it valid until {_day(safe_until)} ({safe_days} days): it expires before the first "
                                        f"increase on file, so the cost it was priced on holds."})
        held = sum((D(ln["qty"]) * D(o["price_to_hold_margin"]) for ln, o in zip(lines, out_lines)), ZERO)
        suggestions.append({"kind": "reprice", "value_usd": out(money.cents(held)),
                            "text": f"Price for the increases: ${money.cents(held):,.2f} total "
                                    f"(+${money.cents(held - revenue):,.2f}) keeps each line's margin through {_day(valid_until)}."})
        clause_lines = "; ".join(
            f"{names.get(c['material_id'], c['material_id'])} quoted at "
            f"${impact.cost_on(conn, c['material_id'], issued):.2f}/lb (supplier price on file: "
            f"${c['cost_per_lb']:.2f}/lb from {_day(c['effective_date'])})" for c in changes)
        suggestions.append({"kind": "clause", "text": (
            f"Material escalation: prices are based on {clause_lines}. If the order is placed after a "
            f"supplier price change takes effect, the price of affected lines will be adjusted by the "
            f"change in material cost per unit.")})

    return {
        "customer": {"id": cust["id"], "name": cust["name"], "tier": cust["tier"], "price_lock_until": lock},
        "issued": issued, "valid_until": valid_until, "margin_floor": margin_floor,
        "value_usd": out(money.cents(revenue)),
        "margin_now": now["margin"], "margin_at_expiry": worst["margin"],
        "below_floor_now": now["below_floor"], "below_floor_at_expiry": worst["below_floor"],
        "at_risk_usd": out(money.cents(D(worst["cost_usd"]) - D(now["cost_usd"]))),
        "changes": [{**c, "material_name": names.get(c["material_id"], c["material_id"])} for c in changes],
        "timeline": timeline,
        "lines": out_lines,
        "price_locked": locked,
        "pending_reviews": pending,
        "suggestions": suggestions,
        "verdict": ("below_floor_now" if now["below_floor"] else
                    "below_floor_after_change" if worst["below_floor"] else
                    "margin_erodes" if changes else "clear"),
    }


def parts_catalog(conn: sqlite3.Connection) -> list[dict]:
    """Parts with their BOM and today's unit cost, for building a quote."""
    from .config import AS_OF
    on = AS_OF.isoformat()
    out_rows = []
    for p in conn.execute("SELECT * FROM parts ORDER BY id"):
        bom = conn.execute("SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?",
                           (p["id"],)).fetchall()
        cost = sum((D(m["lb_per_unit"]) * (1 + D(m["scrap_rate"])) * D(impact.cost_on(conn, m["material_id"], on))
                    for m in bom), ZERO) + D(p["conversion_cost"])
        out_rows.append({"id": p["id"], "name": p["name"], "unit_cost_now": out(money.price(cost)),
                         "materials": [m["material_id"] for m in bom]})
    return out_rows
