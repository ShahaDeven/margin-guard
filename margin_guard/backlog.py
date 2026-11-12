"""Won orders whose material isn't bought yet: increases they will absorb, and what buying now saves.

A won order's price is fixed by the customer's purchase order, so it can't be repriced. If its
material is bought later (when the job is scheduled), every cost increase that takes effect
before that buy date comes straight out of its margin. Nobody is asked about it, so nobody
sees it: impact.py only looks at open quotes, and leakage.py only at the gap between quote and
order.

A won quote with a `material_buy_date` is in the backlog until that material is bought. With
no buy date, material counts as bought on the order date (the assumption leakage.py and
impact.py state), so nothing here changes their figures.

For each backlog order, at the costing supplier's price:

    cost as ordered    the material cost on the order date
    cost at buy date   the cost on the planned buy date, including increases already on file
                       that take effect before it (the Nov 1 notice moves this the day it's processed)
    absorbing          (cost at buy date - cost as ordered) x lb, over every line
    buy now saves      (cost at buy date - cost today) x lb: what pulling the purchase
                       forward to today keeps, when an increase lands before the buy date

`buy_now` records that the material was bought today, at today's cost; `undo_buy` reverses it.
The decision to buy early (cash, storage, shelf life) stays with a person.

    python -m margin_guard.backlog [--db PATH]
"""

import argparse
import sqlite3
from decimal import Decimal

from . import db, impact, money
from .config import AS_OF
from .money import ZERO, D, out

ASSUMPTION = ("A won order's price is fixed, so it absorbs every increase that takes effect before its "
              "material is bought. Costs are at the costing supplier's price; stock on hand isn't modelled.")


class BacklogError(ValueError):
    pass


def _usd(x: Decimal) -> float:
    return out(money.cents(x))


def order(conn: sqlite3.Connection, q: sqlite3.Row, today: str) -> dict:
    """One won order not yet bought: line-by-line cost as ordered, at the buy date, and today."""
    buy_on = q["material_bought_on"] or q["material_buy_date"]
    revenue = cost_ordered = cost_buy = cost_today = cost_planned = ZERO
    lines, changes = [], {}
    for ql in conn.execute(
            """SELECT ql.*, p.name AS part_name FROM quote_lines ql JOIN parts p ON p.id = ql.part_id
               WHERE ql.quote_id = ? ORDER BY ql.id""", (q["id"],)):
        qty = D(ql["qty"])
        revenue += qty * D(ql["unit_price"])
        conversion = qty * D(ql["conversion_cost"])
        cost_ordered += conversion
        cost_buy += conversion
        cost_today += conversion
        cost_planned += conversion
        for m in conn.execute("SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?",
                              (ql["part_id"],)):
            lb = qty * D(m["lb_per_unit"]) * (1 + D(m["scrap_rate"]))
            at_order = D(impact.cost_entry(conn, m["material_id"], q["ordered_date"])[0])
            at_buy, since = impact.cost_entry(conn, m["material_id"], buy_on)
            at_buy = D(at_buy)
            at_today = D(impact.cost_entry(conn, m["material_id"], min(today, buy_on))[0])
            cost_ordered += lb * at_order
            cost_buy += lb * at_buy
            cost_today += lb * at_today
            cost_planned += lb * D(impact.cost_entry(conn, m["material_id"], q["material_buy_date"])[0])
            if at_buy != at_order and since and since > q["ordered_date"]:
                c = changes.setdefault(m["material_id"], {"material_id": m["material_id"], "effective_date": since,
                                                           "cost_as_ordered": out(money.cost(at_order)),
                                                           "cost_at_buy": out(money.cost(at_buy)),
                                                           "absorbing_usd": ZERO, "after_today": since > today})
                c["absorbing_usd"] += lb * (at_buy - at_order)
            lines.append({"line_id": ql["id"], "part_name": ql["part_name"], "material_id": m["material_id"],
                          "lb": out(money.cost(lb)), "cost_as_ordered": out(money.cost(at_order)),
                          "cost_at_buy": out(money.cost(at_buy)), "cost_today": out(money.cost(at_today)),
                          "absorbing_usd": _usd(lb * (at_buy - at_order))})
    margin = lambda cost: out(money.ratio(1 - cost / revenue)) if revenue else 0.0  # noqa: E731
    # Only an increase still to come is worth buying ahead of; a decrease is better waited for.
    upcoming = sorted(c["effective_date"] for c in changes.values() if c["after_today"] and c["absorbing_usd"] > 0)
    saves = max(cost_buy - cost_today, ZERO)
    return {
        "quote_id": q["id"],
        "customer_id": q["customer_id"],
        "customer_name": q["customer_name"],
        "ordered_date": q["ordered_date"],
        "material_buy_date": q["material_buy_date"],
        "material_bought_on": q["material_bought_on"],
        "revenue_usd": _usd(revenue),
        "margin_floor": q["margin_floor"],
        "margin_as_ordered": margin(cost_ordered),
        "margin_at_buy": margin(cost_buy),
        "absorbing_usd": _usd(cost_buy - cost_ordered),
        "buy_now_saves_usd": _usd(saves) if not q["material_bought_on"] and upcoming else 0.0,
        # Bought early: what buying on the planned date would have cost on top of what was paid.
        "saved_usd": _usd(cost_planned - cost_buy) if q["material_bought_on"] else 0.0,
        # Buying before the first increase still to come avoids it.
        "buy_before": upcoming[0] if upcoming and not q["material_bought_on"] else None,
        "below_floor": D(margin(cost_buy)) < D(q["margin_floor"]),
        "changes": [{**c, "absorbing_usd": _usd(c["absorbing_usd"])}
                    for c in sorted(changes.values(), key=lambda c: c["effective_date"])],
        "lines": lines,
    }


def analyze(conn: sqlite3.Connection, today: str | None = None) -> dict:
    today = today or AS_OF.isoformat()
    rows = conn.execute(
        """SELECT q.*, c.name AS customer_name FROM quotes q JOIN customers c ON c.id = q.customer_id
           WHERE q.status = 'won' AND q.material_buy_date IS NOT NULL
             AND (q.material_buy_date > ? OR q.material_bought_on IS NOT NULL)
           ORDER BY q.material_buy_date, q.id""", (today,)).fetchall()
    orders = [order(conn, q, today) for q in rows]
    waiting = [o for o in orders if not o["material_bought_on"]]
    return {
        "as_of": today,
        "assumption": ASSUMPTION,
        "orders": orders,
        "waiting": len(waiting),
        "bought_early": len(orders) - len(waiting),
        "revenue_usd": _usd(sum((D(o["revenue_usd"]) for o in waiting), ZERO)),
        # Increases absorbed, and decreases gained, kept apart so one doesn't hide the other.
        "absorbing_usd": _usd(sum((D(o["absorbing_usd"]) for o in waiting if o["absorbing_usd"] > 0), ZERO)),
        "gaining_usd": _usd(sum((-D(o["absorbing_usd"]) for o in waiting if o["absorbing_usd"] < 0), ZERO)),
        "orders_absorbing": sum(1 for o in waiting if o["absorbing_usd"] > 0),
        "buy_now_saves_usd": _usd(sum((D(o["buy_now_saves_usd"]) for o in waiting), ZERO)),
        "below_floor": sum(1 for o in waiting if o["below_floor"]),
        "saved_by_buying_early_usd": _usd(sum((D(o["saved_usd"]) for o in orders), ZERO)),
    }


def _won(conn: sqlite3.Connection, quote_id: str) -> sqlite3.Row:
    q = conn.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
    if q is None:
        raise BacklogError(f"quote {quote_id} not found")
    if q["status"] != "won" or not q["material_buy_date"]:
        raise BacklogError(f"quote {quote_id} isn't a won order waiting for material")
    return q


def buy_now(conn: sqlite3.Connection, quote_id: str, today: str | None = None) -> dict:
    """Record that this order's material was bought today, at today's cost."""
    today = today or AS_OF.isoformat()
    q = _won(conn, quote_id)
    if q["material_bought_on"]:
        raise BacklogError(f"material for {quote_id} was already bought on {q['material_bought_on']}")
    if q["material_buy_date"] <= today:
        raise BacklogError(f"material for {quote_id} was due {q['material_buy_date']}; it's no longer ahead")
    conn.execute("UPDATE quotes SET material_bought_on = ? WHERE id = ?", (today, quote_id))
    conn.commit()
    return {"quote_id": quote_id, "material_bought_on": today}


def undo_buy(conn: sqlite3.Connection, quote_id: str) -> dict:
    q = _won(conn, quote_id)
    if not q["material_bought_on"]:
        raise BacklogError(f"no early purchase recorded for {quote_id}")
    conn.execute("UPDATE quotes SET material_bought_on = NULL WHERE id = ?", (quote_id,))
    conn.commit()
    return {"quote_id": quote_id, "material_bought_on": None}


def main() -> None:
    ap = argparse.ArgumentParser(description="Won orders whose material isn't bought yet.")
    ap.add_argument("--db", help="database path (default: the demo database)")
    r = analyze(db.connect(ap.parse_args().db))
    print(f"{r['waiting']} won orders waiting for material (${r['revenue_usd']:,.2f}): absorbing "
          f"${r['absorbing_usd']:,.2f} on {r['orders_absorbing']} (decreases give back ${r['gaining_usd']:,.2f}); buying now saves ${r['buy_now_saves_usd']:,.2f}; "
          f"{r['below_floor']} below floor")
    for o in r["orders"]:
        flag = f"bought early {o['material_bought_on']}" if o["material_bought_on"] else (
            f"buy before {o['buy_before']} saves ${o['buy_now_saves_usd']:,.2f}" if o["buy_before"] else "")
        print(f"  {o['quote_id']} {o['customer_name']:<30} buy {o['material_buy_date']}  absorbing "
              f"${o['absorbing_usd']:>9,.2f}  margin {o['margin_as_ordered']:.1%} -> {o['margin_at_buy']:.1%}  {flag}")


if __name__ == "__main__":
    main()
