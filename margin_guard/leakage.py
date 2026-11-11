"""Margin leakage: how much margin won jobs lost because costs moved after they were quoted.

For every won quote, compare the material cost it was priced on (quote_lines.
material_cost_basis) with the cost when the customer placed the order, at the
costing supplier's price (impact.cost_on). The difference, times quantity, is
margin that leaked: the job shipped at the old price on new costs.

Same assumption as impact.py, stated in every report: replacement-cost
exposure, i.e. material for an order is bought when the order is placed.
Stock bought earlier at the old cost is not modelled, so this is the margin
at risk at replacement cost, not an accounting figure.

Every leaked dollar here comes from a cost change that took effect between the
quote going out and the order coming in: the window in which a revised quote
or a call to the customer could still have recovered it, unless the customer
had a price lock covering the order date. Locked jobs are counted separately
(locked_usd): that margin was given away by the contract, not missed.

    python -m margin_guard.leakage [--db PATH]
"""

import argparse
import sqlite3
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from . import catalog, db, impact, money
from .config import DB_PATH
from .money import ZERO, D, out

ASSUMPTION = ("Replacement cost: material for an order is costed at the costing supplier's price on the "
              "order date. Stock already on hand at an older cost is not modelled.")


def _usd(x: Decimal) -> float:
    return out(money.cents(x))


def supplier_history_row(conn: sqlite3.Connection, material_id: str, vendor_id: str, on: str) -> dict | None:
    """The price-history row behind one supplier's own price on `on` (impact.supplier_cost),
    so a price and the evidence shown for it always come from the same supplier."""
    r = conn.execute(
        """SELECT h.id, h.cost_per_lb, h.effective_date, h.vendor_id, v.name AS vendor_name,
                  json_extract(e.payload, '$.email_id') AS email_id
           FROM material_price_history h
           LEFT JOIN vendors v ON v.id = h.vendor_id
           LEFT JOIN events e ON e.id = h.source_event_id
           WHERE h.material_id = ? AND h.vendor_id = ? AND h.effective_date <= ?
           ORDER BY h.effective_date DESC, h.id DESC LIMIT 1""",
        (material_id, vendor_id, on),
    ).fetchone()
    return dict(r) if r else None


def history_row(conn: sqlite3.Connection, material_id: str, on: str) -> dict | None:
    """The price-history row a cost on `on` came from: the same row impact.cost_entry
    picks (costing supplier, or a shop entry), with its supplier and source email."""
    costing = catalog.costing_vendor(conn, material_id)
    r = conn.execute(
        """SELECT h.id, h.cost_per_lb, h.effective_date, h.vendor_id, v.name AS vendor_name,
                  json_extract(e.payload, '$.email_id') AS email_id
           FROM material_price_history h
           LEFT JOIN vendors v ON v.id = h.vendor_id
           LEFT JOIN events e ON e.id = h.source_event_id
           WHERE h.material_id = ? AND h.effective_date <= ?
             AND (h.vendor_id IS NULL OR h.vendor_id = ?)
           ORDER BY h.effective_date DESC, h.id DESC LIMIT 1""",
        (material_id, on, costing),
    ).fetchone()
    return dict(r) if r else None


def job(conn: sqlite3.Connection, q: sqlite3.Row) -> dict:
    """One won quote: quoted vs realized material cost, and which materials moved."""
    revenue = quoted_cost = leak = ZERO
    by_material: dict[str, Decimal] = defaultdict(lambda: ZERO)
    gaps: set[str] = set()
    # One entry per quote line x material: the whole calculation, row by row, so
    # every leaked dollar can be traced to the price-history rows behind it.
    trace: list[dict] = []
    for ql in conn.execute(
            """SELECT ql.*, p.name AS part_name FROM quote_lines ql JOIN parts p ON p.id = ql.part_id
               WHERE ql.quote_id = ? ORDER BY ql.id""", (q["id"],)):
        qty = D(ql["qty"])
        bom = conn.execute("SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?",
                           (ql["part_id"],)).fetchall()
        realized_material = ZERO
        for m in bom:
            lb = D(m["lb_per_unit"]) * (1 + D(m["scrap_rate"]))
            quote_cost, quote_since = impact.cost_entry(conn, m["material_id"], q["issued_date"])
            order_cost, order_since = impact.cost_entry(conn, m["material_id"], q["ordered_date"])
            if quote_since is None or order_since is None:
                # No history that far back: the fallback is today's cost, which
                # would invent a move. Flag the job instead of guessing.
                gaps.add(m["material_id"])
            at_quote, at_order = D(quote_cost), D(order_cost)
            realized_material += lb * at_order
            moved = qty * lb * (at_order - at_quote)
            if at_order != at_quote:
                by_material[m["material_id"]] += moved
            trace.append({
                "line_id": ql["id"], "part_id": ql["part_id"], "part_name": ql["part_name"],
                "qty": ql["qty"], "material_id": m["material_id"],
                "lb_per_unit": m["lb_per_unit"], "scrap_rate": m["scrap_rate"],
                "cost_at_quote": out(money.cost(at_quote)), "cost_at_order": out(money.cost(at_order)),
                "quote_row": history_row(conn, m["material_id"], q["issued_date"]),
                "order_row": history_row(conn, m["material_id"], q["ordered_date"]),
                "leak_usd": _usd(moved),
            })
        revenue += qty * D(ql["unit_price"])
        quoted_cost += qty * (D(ql["material_cost_basis"]) + D(ql["conversion_cost"]))
        leak += qty * (realized_material - D(ql["material_cost_basis"]))
    realized_cost = quoted_cost + leak
    margin_quoted = money.ratio(1 - quoted_cost / revenue) if revenue else ZERO
    margin_realized = money.ratio(1 - realized_cost / revenue) if revenue else ZERO
    # Price history explains the leak material by material; anything left over is
    # the quoted basis differing from history at the quote date (an estimator's own number).
    residual = leak - sum(by_material.values(), ZERO)
    return {
        "quote_id": q["id"],
        "customer_id": q["customer_id"],
        "customer_name": q["customer_name"],
        "issued_date": q["issued_date"],
        "ordered_date": q["ordered_date"],
        "revenue_usd": _usd(revenue),
        "margin_floor": q["margin_floor"],
        "margin_quoted": out(margin_quoted),
        "margin_realized": out(margin_realized),
        "leak_usd": _usd(leak),
        "below_floor": margin_realized < D(q["margin_floor"]) <= margin_quoted,
        "by_material": {m: _usd(v) for m, v in sorted(by_material.items())},
        "basis_difference_usd": _usd(residual),
        "history_gaps": sorted(gaps),
        # A contract price lock covering the order date: the job could not have been
        # repriced, so its leak was locked in, not recoverable.
        "price_locked": bool(q["price_lock_until"] and q["price_lock_until"] >= q["ordered_date"]),
        "price_lock_until": q["price_lock_until"],
        "trace": trace,
    }


def analyze(conn: sqlite3.Connection) -> dict:
    """The leakage report over every won quote with an order date."""
    rows = conn.execute(
        """SELECT q.*, c.name AS customer_name, c.price_lock_until FROM quotes q JOIN customers c ON c.id = q.customer_id
           WHERE q.status = 'won' AND q.ordered_date IS NOT NULL ORDER BY q.ordered_date, q.id"""
    ).fetchall()
    analyzed = [job(conn, q) for q in rows]
    jobs = [j for j in analyzed if not j["history_gaps"]]
    skipped = [j for j in analyzed if j["history_gaps"]]
    names = dict(conn.execute("SELECT id, name FROM materials").fetchall())

    lost = sum((D(j["leak_usd"]) for j in jobs if j["leak_usd"] > 0), ZERO)
    locked = sum((D(j["leak_usd"]) for j in jobs if j["leak_usd"] > 0 and j["price_locked"]), ZERO)
    gained = sum((-D(j["leak_usd"]) for j in jobs if j["leak_usd"] < 0), ZERO)
    revenue = sum((D(j["revenue_usd"]) for j in jobs), ZERO)

    materials: dict[str, dict] = {}
    customers: dict[str, dict] = {}
    months: dict[str, dict] = {}
    for j in jobs:
        for m, usd in j["by_material"].items():
            row = materials.setdefault(m, {"material_id": m, "material_name": names.get(m, m),
                                           "leak_usd": ZERO, "jobs": 0})
            row["leak_usd"] += D(usd)
            row["jobs"] += 1
        if j["leak_usd"]:
            c = customers.setdefault(j["customer_id"], {"customer_id": j["customer_id"],
                                                        "customer_name": j["customer_name"],
                                                        "leak_usd": ZERO, "jobs": 0})
            c["leak_usd"] += D(j["leak_usd"])
            c["jobs"] += 1
        mo = months.setdefault(j["ordered_date"][:7], {"month": j["ordered_date"][:7], "leak_usd": ZERO,
                                                       "jobs": 0, "revenue_usd": ZERO})
        mo["leak_usd"] += D(j["leak_usd"])
        mo["revenue_usd"] += D(j["revenue_usd"])
        mo["jobs"] += 1

    def finish(rows: list[dict]) -> list[dict]:
        return [{**r, **{k: _usd(v) for k, v in r.items() if isinstance(v, Decimal)}} for r in rows]

    weighted = lambda key: out(money.ratio(  # noqa: E731
        sum((D(j[key]) * D(j["revenue_usd"]) for j in jobs), ZERO) / revenue)) if revenue else 0.0
    return {
        "assumption": ASSUMPTION,
        "period": {"from": jobs[0]["ordered_date"], "to": jobs[-1]["ordered_date"]} if jobs else None,
        "won_jobs": len(jobs),
        # Won jobs left out because a material had no cost history back to the quote date.
        "skipped_jobs": [{"quote_id": j["quote_id"], "materials": j["history_gaps"]} for j in skipped],
        "jobs_with_cost_moves": sum(1 for j in jobs if j["leak_usd"]),
        "jobs_leaked": sum(1 for j in jobs if j["leak_usd"] > 0),
        "revenue_usd": _usd(revenue),
        "leaked_usd": _usd(lost),
        "gained_usd": _usd(gained),
        "net_leaked_usd": _usd(lost - gained),
        # Of the leaked dollars: what a revised quote could have recovered, and what a
        # customer price lock had already fixed.
        "recoverable_usd": _usd(lost - locked),
        "locked_usd": _usd(locked),
        "jobs_locked": sum(1 for j in jobs if j["leak_usd"] > 0 and j["price_locked"]),
        "margin_quoted": weighted("margin_quoted"),
        "margin_realized": weighted("margin_realized"),
        "below_floor_jobs": sum(1 for j in jobs if j["below_floor"]),
        "by_material": finish(sorted(materials.values(), key=lambda r: -r["leak_usd"])),
        "by_customer": finish(sorted(customers.values(), key=lambda r: -r["leak_usd"])),
        "by_month": finish(sorted(months.values(), key=lambda r: r["month"])),
        "top_jobs": sorted(jobs, key=lambda j: -j["leak_usd"])[:10],
        "jobs": jobs,
    }


def report_markdown(r: dict) -> str:
    if not r["won_jobs"]:
        return "No won quotes with an order date; nothing to analyze."
    lines = [
        f"## Margin leakage, {r['period']['from']} to {r['period']['to']}",
        "",
        f"- Won jobs: **{r['won_jobs']}** (${r['revenue_usd']:,.2f} revenue); "
        f"costs moved between quote and order on **{r['jobs_with_cost_moves']}**",
        f"- Margin leaked: **${r['leaked_usd']:,.2f}** on {r['jobs_leaked']} jobs; "
        f"gained from decreases: ${r['gained_usd']:,.2f}; net **${r['net_leaked_usd']:,.2f}**",
        f"- Recoverable by a revised quote: **${r['recoverable_usd']:,.2f}**; locked in by customer price locks: "
        f"${r['locked_usd']:,.2f} on {r['jobs_locked']} jobs",
        f"- Margin as quoted {r['margin_quoted']:.1%} -> as ordered {r['margin_realized']:.1%} (revenue-weighted)",
        f"- Jobs that ended below their margin floor: **{r['below_floor_jobs']}**",
        f"- Assumption: {r['assumption']}",
        *([f"- Left out (no cost history back to the quote date): {len(r['skipped_jobs'])} jobs"]
          if r["skipped_jobs"] else []),
        "",
        "| Material | Leaked | Jobs |", "|---|---|---|",
        *[f"| {m['material_name']} | ${m['leak_usd']:,.2f} | {m['jobs']} |" for m in r["by_material"]],
        "",
        "| Job | Customer | Quoted -> ordered | Margin | Leaked |", "|---|---|---|---|---|",
        *[f"| {j['quote_id']} | {j['customer_name']} | {j['issued_date']} -> {j['ordered_date']} | "
          f"{j['margin_quoted']:.1%} -> {j['margin_realized']:.1%}{' (below floor)' if j['below_floor'] else ''} | "
          f"${j['leak_usd']:,.2f} |" for j in r["top_jobs"]],
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()
    print(report_markdown(analyze(db.connect(args.db))))


if __name__ == "__main__":
    main()
