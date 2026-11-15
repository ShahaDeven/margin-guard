"""Load the synthetic demo shop into a local Odoo, through the same JSON-2 client the connector uses.

    python -m margin_guard.erp setup      # runs this as its last step
    python -m margin_guard.erp load       # just this, against a running Odoo

The shop is built fresh from margin_guard.seed (the state before the supplier inbox is
read), so Odoo starts where the demo starts and your own database is never touched. How
each Margin Guard record lands in Odoo:

    supplier            res.partner, a company with supplier rank; `ref` holds the id (V-MWP)
    customer            res.partner, a company with customer rank and a "Key account" tag
                        where it applies; the buyer is a child contact, the price lock and
                        contract note go in the internal note
    account manager     res.users, so a "call the customer first" task can be assigned to them
    material            product.product in pounds, purchasable, internal reference MAT-...
    supplier price      product.supplierinfo: one dated line per price in the history, ended
                        the day before the next one; the costing supplier gets sequence 1
    part                product.product in units, sellable; its cost is today's BOM cost
    BOM                 mrp.bom; each line is the gross pounds a unit consumes, scrap included,
                        because Odoo's BOM line has no scrap rate
    open quote          sale.order (quotation) named with the quote id, valid until its date;
                        each line carries price and cost when quoted (Sales margin's
                        purchase_price), so Odoo shows the quoted margin too
    won quote           confirmed sale.order, order date set back to when it was ordered
    lost quote          cancelled sale.order
    invoice line        posted vendor bill (account.move), converted to pounds and $/lb; a line
                        that matches no material (freight) goes in as billed, with no product

What stays in Margin Guard: each quote's margin floor and a part's conversion cost have no
standard Odoo field, and price changes from the supplier inbox are written by the connector
only after a person approves them.
"""

import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .. import catalog, db, invoices, seed
from ..config import ROOT
from ..money import D, cost, price
from ..units import LB_PER_UNIT, to_cost_per_lb
from .odoo import OdooClient

DEMO_INVOICES = ROOT / "data" / "invoices_demo.csv"
BATCH = 40


def _batched(rows: list, n: int = BATCH):
    for i in range(0, len(rows), n):
        yield rows[i:i + n]


def _slug(name: str) -> str:
    return "".join(ch for ch in name.lower().replace(" ", ".") if ch.isalnum() or ch == ".")


def already_loaded(c: OdooClient) -> bool:
    return bool(c.call("res.partner", "search_count", domain=[["ref", "=", "V-MWP"]]))


def load(c: OdooClient, say=print) -> dict:
    if already_loaded(c):
        say("The demo shop is already in Odoo; nothing loaded. (Remove the Docker volumes to start over.)")
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        shop = db.connect(Path(tmp) / "shop.db")
        seed.build(shop)
        counts = _load(c, shop, say)
        shop.close()
    return counts


def _load(c: OdooClient, shop, say) -> dict:
    # Margin Guard keeps costs to 6 decimals and quantities to 4; Odoo's defaults are 2.
    for name, digits in (("Product Price", 6), ("Product Unit", 4)):
        ids = [r["id"] for r in c.search_read("decimal.precision", [["name", "=", name]], ["id"])]
        c.write("decimal.precision", ids, {"digits": digits})
    lb, unit = c.xmlid("uom", "product_uom_lb"), c.xmlid("uom", "product_uom_unit")
    counts: dict[str, int] = {}

    # ---------------------------------------------------------------- partners and people
    vendors = shop.execute("SELECT * FROM vendors ORDER BY id").fetchall()
    vids = c.create("res.partner", [{"name": v["name"], "ref": v["id"], "is_company": True, "supplier_rank": 1,
                                     "email": f"orders@{v['email_domain']}", "website": v["email_domain"]} for v in vendors])
    vendor_id = {v["id"]: i for v, i in zip(vendors, vids)}

    key_tag = c.create("res.partner.category", [{"name": "Key account"}])[0]
    customers = shop.execute("SELECT * FROM customers ORDER BY id").fetchall()
    managers = sorted({(x["account_manager"], x["account_manager_phone"]) for x in customers if x["account_manager"]})
    uids = c.create("res.users", [{"name": n, "login": f"{_slug(n)}@shop.example", "phone": p} for n, p in managers])
    user_id = {n: i for (n, _), i in zip(managers, uids)}
    cids = c.create("res.partner", [{
        "name": x["name"], "ref": x["id"], "is_company": True, "customer_rank": 1,
        "user_id": user_id.get(x["account_manager"]) or False,
        "category_id": [[6, 0, [key_tag]]] if x["tier"] == "key" else [],
        "comment": "<br/>".join(filter(None, [
            f"Price lock until {x['price_lock_until']}." if x["price_lock_until"] else "",
            f"Contract note: {x['contract_note']}" if x["contract_note"] else ""])),
    } for x in customers])
    customer_id = {x["id"]: i for x, i in zip(customers, cids)}
    c.create("res.partner", [{"name": x["buyer_name"], "parent_id": customer_id[x["id"]], "type": "contact",
                              "function": "Buyer", "email": x["buyer_email"], "phone": x["buyer_phone"]}
                             for x in customers if x["buyer_name"]])

    manager_of = {x["id"]: user_id.get(x["account_manager"]) for x in customers}
    counts.update(suppliers=len(vids), customers=len(cids), account_managers=len(uids))
    say(f"  partners: {len(vids)} suppliers, {len(cids)} customers with buyers, {len(uids)} account managers")

    # ---------------------------------------------------------------- products
    materials = shop.execute("SELECT * FROM materials ORDER BY id").fetchall()
    mids = c.create("product.product", [{
        "name": m["name"], "default_code": m["id"], "type": "consu", "is_storable": True,
        "uom_id": lb, "purchase_ok": True, "sale_ok": False, "standard_price": m["cost_per_lb"],
    } for m in materials])
    material_id = {m["id"]: i for m, i in zip(materials, mids)}
    mat_tmpl = {r["id"]: r["product_tmpl_id"][0] for r in c.search_read("product.product", [["id", "in", mids]], ["product_tmpl_id"])}

    bom = defaultdict(list)
    for r in shop.execute("SELECT * FROM part_materials ORDER BY part_id, material_id"):
        bom[r["part_id"]].append(r)
    cost_now = {m["id"]: D(m["cost_per_lb"]) for m in materials}
    parts = shop.execute("SELECT * FROM parts ORDER BY id").fetchall()
    gross = lambda r: D(r["lb_per_unit"]) * (1 + D(r["scrap_rate"]))  # noqa: E731
    pids = c.create("product.product", [{
        "name": p["name"], "default_code": p["id"], "type": "consu", "is_storable": True, "uom_id": unit,
        "sale_ok": True, "purchase_ok": False,
        "standard_price": float(price(D(p["conversion_cost"]) + sum(gross(r) * cost_now[r["material_id"]] for r in bom[p["id"]]))),
    } for p in parts])
    part_id = {p["id"]: i for p, i in zip(parts, pids)}
    part_tmpl = {r["id"]: r["product_tmpl_id"][0] for r in c.search_read("product.product", [["id", "in", pids]], ["product_tmpl_id"])}
    counts.update(materials=len(mids), parts=len(pids))
    say(f"  products: {len(mids)} materials in lb, {len(pids)} parts")

    # ---------------------------------------------------------------- supplier price history
    primary = {(r["material_id"], r["vendor_id"]): r["is_primary"] for r in shop.execute("SELECT * FROM material_vendors")}
    hist = defaultdict(list)
    for r in shop.execute("SELECT * FROM material_price_history WHERE vendor_id IS NOT NULL ORDER BY effective_date, id"):
        hist[(r["material_id"], r["vendor_id"])].append(r)
    lines = []
    for (mat, ven), rows in hist.items():
        for i, r in enumerate(rows):
            nxt = rows[i + 1]["effective_date"] if i + 1 < len(rows) else None
            lines.append({
                "partner_id": vendor_id[ven], "product_tmpl_id": mat_tmpl[material_id[mat]], "product_uom_id": lb,
                "price": float(cost(r["cost_per_lb"])), "min_qty": 0, "date_start": r["effective_date"],
                "date_end": (date.fromisoformat(nxt) - timedelta(days=1)).isoformat() if nxt else False,
                "sequence": 1 if primary.get((mat, ven)) else 10,
            })
    for chunk in _batched(lines):
        c.create("product.supplierinfo", chunk)
    counts["supplier_prices"] = len(lines)
    say(f"  supplier prices: {len(lines)} dated lines")

    # ---------------------------------------------------------------- BOMs
    boms = [{"product_tmpl_id": part_tmpl[part_id[p]], "product_qty": 1, "type": "normal", "code": p,
             "bom_line_ids": [[0, 0, {"product_id": material_id[r["material_id"]], "product_uom_id": lb,
                                      "product_qty": float(gross(r).quantize(D("0.0001")))}] for r in rows]}
            for p, rows in bom.items()]
    for chunk in _batched(boms):
        c.create("mrp.bom", chunk)
    counts["boms"] = len(boms)
    say(f"  BOMs: {len(boms)}")

    # ---------------------------------------------------------------- quotes
    quotes = shop.execute("SELECT * FROM quotes ORDER BY id").fetchall()
    qlines = defaultdict(list)
    for r in shop.execute("SELECT * FROM quote_lines ORDER BY id"):
        qlines[r["quote_id"]].append(r)
    order_id: dict[str, int] = {}
    for chunk in _batched(quotes, 25):
        ids = c.create("sale.order", [{
            "name": q["id"], "client_order_ref": q["id"], "partner_id": customer_id[q["customer_id"]],
            "user_id": manager_of.get(q["customer_id"]) or False,
            "date_order": f"{q['issued_date']} 08:00:00", "validity_date": q["valid_until"],
            "order_line": [[0, 0, {"product_id": part_id[ln["part_id"]], "product_uom_qty": ln["qty"],
                                   "price_unit": ln["unit_price"],
                                   "purchase_price": float(price(D(ln["material_cost_basis"]) + D(ln["conversion_cost"])))}]
                           for ln in qlines[q["id"]]],
        } for q in chunk])
        order_id.update({q["id"]: i for q, i in zip(chunk, ids)})
    won = [q for q in quotes if q["status"] == "won"]
    lost = [q for q in quotes if q["status"] in ("lost", "expired")]
    for q in won:
        c.call("sale.order", "action_confirm", ids=[order_id[q["id"]]])
        # Confirming stamps today's date; put the real order date back.
        c.write("sale.order", [order_id[q["id"]]], {"date_order": f"{q['ordered_date']} 08:00:00"})
    if lost:
        c.call("sale.order", "action_cancel", ids=[order_id[q["id"]] for q in lost],
               context={"disable_cancel_warning": True})
    counts.update(quotes_open=len(quotes) - len(won) - len(lost), orders_won=len(won), quotes_lost=len(lost))
    say(f"  quotes: {counts['quotes_open']} open, {len(won)} confirmed orders, {len(lost)} cancelled")

    # ---------------------------------------------------------------- vendor bills
    rows = invoices.read(shop, DEMO_INVOICES)
    by_bill = defaultdict(list)
    for r in rows:
        by_bill[(r["vendor_id"], r["invoice_no"], r["invoice_date"])].append(r)
    bills = []
    for (ven, no, day), items in by_bill.items():
        bill_lines = []
        for r in items:
            match = catalog.resolve_material(shop, r["item"], ven).material_id
            if match not in material_id:
                # Freight, or a name that could be two materials: no product to price it against,
                # so it goes in exactly as billed, as a plain charge line.
                bill_lines.append([0, 0, {"name": r["item"], "quantity": r["qty"], "price_unit": r["unit_price"]}])
                continue
            pack = r.get("pack_qty")
            lbs = D(r["qty"]) * (D(pack) if pack else 1) * LB_PER_UNIT[r["unit"]]
            bill_lines.append([0, 0, {
                "name": r["item"], "product_id": material_id[match], "product_uom_id": lb,
                "quantity": float(lbs.quantize(D("0.0001"))),
                "price_unit": float(to_cost_per_lb(r["unit_price"], r["unit"], pack)),
            }])
        bills.append({"move_type": "in_invoice", "partner_id": vendor_id[ven], "ref": no,
                      "invoice_date": day, "invoice_line_ids": bill_lines})
    bill_ids = c.create("account.move", bills)
    c.call("account.move", "action_post", ids=bill_ids)
    counts["vendor_bills"] = len(bill_ids)
    say(f"  vendor bills: {len(bill_ids)} posted, {len(rows)} lines")
    return counts
