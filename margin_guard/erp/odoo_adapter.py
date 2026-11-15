"""Odoo 19 as an ERP adapter: reads the shop out of Odoo and hands it to the sync in Margin
Guard's terms (see adapter.py).

Mapping decisions, each the opposite direction of odoo_seed.py:

    units        a price or quantity in kg, t or lb becomes pounds and $/lb; any other unit
                 (an ounce, a roll) is skipped and reported, never guessed
    currency     a supplier price in anything but USD is skipped and reported; there is no FX
    price breaks a supplier price with a minimum quantity is a break, not the price; skipped
                 and reported (Margin Guard costs at the base price)
    costing      the costing supplier is the one with the lowest sequence on that material's
                 price lines, which is how Odoo itself picks the vendor for a purchase
    quote state  draft and sent are open; sale is won, its order date the date ordered;
                 cancel is lost
    quote date   confirming a quotation overwrites its date with the confirmation date, so
                 Odoo no longer knows when a won order was quoted: the adapter says so
                 (issued_date None) instead of passing the order date off as the quote date
    bills        posted vendor bills only; a line linked to a product carries that material
                 so the invoice check can judge it without guessing from the description
"""

import re
from collections import defaultdict

from ..units import LB_PER_UNIT
from .odoo import OdooClient

# Odoo unit names (uom.uom.name) Margin Guard can convert, and what they are in units.py.
UOM = {"lb": "lb", "lbs": "lb", "kg": "kg", "t": "metric_ton", "ton": "short_ton", "cwt": "cwt"}
STATE = {"draft": "open", "sent": "open", "sale": "won", "done": "won", "cancel": "lost"}


def _since(domain: list, since: str | None) -> list:
    return domain + ([["write_date", ">=", since]] if since else [])


def _text(html: str | bool) -> str:
    return re.sub(r"\s+\n", "\n", re.sub(r"<[^>]+>", "\n", html or "")).strip()


class OdooAdapter:
    system = "odoo"

    def __init__(self, client: OdooClient | None = None):
        self.c = client or OdooClient()
        self._skipped: list[str] = []
        self._ref: dict[tuple[str, int], str] = {}

    def skipped(self) -> list[str]:
        out, self._skipped = self._skipped, []
        return out

    # ---------------------------------------------------------------- helpers
    def _refs(self, model: str, ids: list[int], field: str, prefix: str) -> dict[int, str]:
        """Natural keys for ERP ids (partner `ref`, product `default_code`), cached."""
        need = [i for i in set(ids) if i and (model, i) not in self._ref]
        if need:
            for r in self.c.search_read(model, [["id", "in", need]], [field]):
                self._ref[(model, r["id"])] = r[field] or f"{prefix}-ODOO-{r['id']}"
        return {i: self._ref[(model, i)] for i in set(ids) if i}

    def _unit(self, uom: list | bool, what: str) -> str | None:
        name = (uom[1] if uom else "").strip().lower()
        unit = UOM.get(name)
        if unit is None:
            self._skipped.append(f"{what}: unit {name or 'none'!r} isn't a weight Margin Guard can convert")
        return unit

    def _search(self, model: str, domain: list, fields: list[str]) -> list[dict]:
        return self.c.search_read(model, domain, fields + ["write_date"], order="write_date asc, id asc")

    # ---------------------------------------------------------------- kinds
    def pull(self, kind: str, since: str | None) -> list[dict]:
        return getattr(self, f"_{kind}")(since)

    def _supplier(self, since):
        rows = self._search("res.partner", _since([["supplier_rank", ">", 0], ["is_company", "=", True]], since),
                            ["ref", "name", "email", "website"])
        out = []
        for r in rows:
            domain = (r["website"] or "").replace("https://", "").replace("http://", "").strip("/") \
                or (r["email"] or "").rsplit("@", 1)[-1]
            out.append({"erp_id": r["id"], "write_date": r["write_date"], "ref": r["ref"] or f"V-ODOO-{r['id']}",
                        "name": r["name"], "email_domain": domain.lower() or f"odoo-{r['id']}.invalid"})
        return out

    def _customer(self, since):
        base = [["customer_rank", ">", 0], ["is_company", "=", True]]
        rows = self._search("res.partner", _since(base, since), ["ref", "name", "category_id", "comment", "user_id"])
        if since:
            # A buyer edited on its own changes the child, not the company: pick those companies up too.
            moved = {r["parent_id"][0] for r in self.c.search_read(
                "res.partner", [["parent_id", "!=", False], ["write_date", ">=", since]], ["parent_id"])}
            extra = moved - {r["id"] for r in rows}
            if extra:
                rows += self._search("res.partner", base + [["id", "in", sorted(extra)]],
                                     ["ref", "name", "category_id", "comment", "user_id"])
        if not rows:
            return []
        key = {t["id"] for t in self.c.search_read("res.partner.category", [["name", "=", "Key account"]], ["id"])}
        buyers = {}
        for b in self.c.search_read("res.partner", [["parent_id", "in", [r["id"] for r in rows]], ["function", "ilike", "buyer"]],
                                    ["parent_id", "name", "email", "phone"]):
            buyers.setdefault(b["parent_id"][0], b)
        users = {u["id"]: u for u in self.c.search_read(
            "res.users", [["id", "in", sorted({r["user_id"][0] for r in rows if r["user_id"]})]], ["name", "phone"])}
        out = []
        for r in rows:
            note = _text(r["comment"])
            lock = re.search(r"Price lock until (\d{4}-\d{2}-\d{2})", note)
            contract = re.search(r"Contract note:\s*(.+)", note)
            b = buyers.get(r["id"], {})
            u = users.get(r["user_id"][0]) if r["user_id"] else None
            out.append({"erp_id": r["id"], "write_date": r["write_date"], "ref": r["ref"] or f"C-ODOO-{r['id']}",
                        "name": r["name"], "tier": "key" if key & set(r["category_id"]) else "standard",
                        "price_lock_until": lock.group(1) if lock else None,
                        "contract_note": contract.group(1).strip() if contract else None,
                        "buyer_name": b.get("name"), "buyer_email": b.get("email") or None, "buyer_phone": b.get("phone") or None,
                        "account_manager": u["name"] if u else None, "account_manager_phone": (u or {}).get("phone") or None})
        return out

    def _material(self, since):
        rows = self._search("product.product", _since([["purchase_ok", "=", True], ["sale_ok", "=", False]], since),
                            ["default_code", "name", "standard_price", "uom_id"])
        out = []
        for r in rows:
            ref = r["default_code"] or f"MAT-ODOO-{r['id']}"
            unit = self._unit(r["uom_id"], f"material {ref}")
            if unit is None:
                continue
            out.append({"erp_id": r["id"], "write_date": r["write_date"], "ref": ref, "name": r["name"],
                        "cost_per_lb": float(r["standard_price"]) / float(LB_PER_UNIT[unit])})
        return out

    def _part(self, since):
        rows = self._search("product.product", _since([["sale_ok", "=", True]], since), ["default_code", "name"])
        return [{"erp_id": r["id"], "write_date": r["write_date"], "ref": r["default_code"] or f"P-ODOO-{r['id']}",
                 "name": r["name"]} for r in rows]

    def _supplier_price(self, since):
        fields = ["partner_id", "product_tmpl_id", "price", "date_start", "min_qty", "sequence", "currency_id", "product_uom_id"]
        rows = self._search("product.supplierinfo", _since([], since), fields)
        if not rows:
            return []
        tmpls = sorted({r["product_tmpl_id"][0] for r in rows})
        # The costing supplier is decided over all of a material's lines, not just the changed ones.
        everything = self.c.search_read("product.supplierinfo", [["product_tmpl_id", "in", tmpls]], ["partner_id", "product_tmpl_id", "sequence"])
        costing = {}
        for r in sorted(everything, key=lambda r: (r["sequence"], r["id"])):
            costing.setdefault(r["product_tmpl_id"][0], r["partner_id"][0])
        codes = self._refs("product.template", tmpls, "default_code", "MAT")
        vendors = self._refs("res.partner", [r["partner_id"][0] for r in rows], "ref", "V")
        out = []
        for r in rows:
            mat, ven = codes[r["product_tmpl_id"][0]], vendors[r["partner_id"][0]]
            what = f"{ven} price for {mat} from {r['date_start'] or r['write_date'][:10]}"
            if r["currency_id"] and r["currency_id"][1] != "USD":
                self._skipped.append(f"{what}: in {r['currency_id'][1]}; Margin Guard has no FX conversion")
                continue
            if r["min_qty"] and r["min_qty"] > 0:
                self._skipped.append(f"{what}: a break at {r['min_qty']:g}+, not the base price")
                continue
            unit = self._unit(r["product_uom_id"], what)
            if unit is None:
                continue
            out.append({"erp_id": r["id"], "write_date": r["write_date"], "material_ref": mat, "supplier_ref": ven,
                        "cost_per_lb": round(float(r["price"]) / float(LB_PER_UNIT[unit]), 6),
                        "effective_date": r["date_start"] or r["write_date"][:10],
                        "is_costing": costing.get(r["product_tmpl_id"][0]) == r["partner_id"][0]})
        return out

    def _bom(self, since):
        boms = self._search("mrp.bom", _since([], since), ["product_tmpl_id", "product_qty"])
        if not boms:
            return []
        lines = self.c.search_read("mrp.bom.line", [["bom_id", "in", [b["id"] for b in boms]]],
                                   ["bom_id", "product_id", "product_qty", "product_uom_id"])
        mats = self._refs("product.product", [ln["product_id"][0] for ln in lines], "default_code", "MAT")
        parts = self._refs("product.template", [b["product_tmpl_id"][0] for b in boms], "default_code", "P")
        by_bom = defaultdict(list)
        for ln in lines:
            by_bom[ln["bom_id"][0]].append(ln)
        out = []
        for b in boms:
            part, qty, ok, items = parts[b["product_tmpl_id"][0]], b["product_qty"] or 1, True, []
            for ln in by_bom[b["id"]]:
                unit = self._unit(ln["product_uom_id"], f"BOM {part}, {mats[ln['product_id'][0]]}")
                if unit is None:
                    ok = False
                    break
                items.append((mats[ln["product_id"][0]], round(ln["product_qty"] * float(LB_PER_UNIT[unit]) / qty, 4)))
            if ok:
                out.append({"erp_id": b["id"], "write_date": b["write_date"], "part_ref": part, "lines": sorted(items)})
        return out

    def _quote(self, since):
        orders = self._search("sale.order", _since([], since), ["name", "partner_id", "state", "date_order", "validity_date"])
        if not orders:
            return []
        lines = self.c.search_read("sale.order.line", [["order_id", "in", [o["id"] for o in orders]], ["display_type", "=", False]],
                                   ["order_id", "product_id", "product_uom_qty", "price_unit", "purchase_price"], order="id asc")
        parts = self._refs("product.product", [ln["product_id"][0] for ln in lines if ln["product_id"]], "default_code", "P")
        customers = self._refs("res.partner", [o["partner_id"][0] for o in orders], "ref", "C")
        by_order = defaultdict(list)
        for ln in lines:
            if ln["product_id"]:
                by_order[ln["order_id"][0]].append({"erp_id": ln["id"], "part_ref": parts[ln["product_id"][0]],
                                                    "qty": ln["product_uom_qty"], "unit_price": ln["price_unit"],
                                                    "cost_each": ln["purchase_price"]})
        out = []
        for o in orders:
            status = STATE.get(o["state"])
            if status is None:
                self._skipped.append(f"quote {o['name']}: state {o['state']!r} has no meaning in Margin Guard")
                continue
            day = o["date_order"][:10]
            out.append({"erp_id": o["id"], "write_date": o["write_date"], "ref": o["name"], "customer_ref": customers[o["partner_id"][0]],
                        "status": status, "issued_date": None if status == "won" else day,
                        "valid_until": o["validity_date"] or day,
                        "ordered_date": day if status == "won" else None, "lines": by_order[o["id"]]})
        return out

    def _bill_line(self, since):
        domain = [["move_id.move_type", "=", "in_invoice"], ["parent_state", "=", "posted"], ["display_type", "=", "product"]]
        rows = self._search("account.move.line", _since(domain, since),
                            ["move_id", "name", "product_id", "quantity", "price_unit", "product_uom_id"])
        if not rows:
            return []
        moves = {m["id"]: m for m in self.c.search_read("account.move", [["id", "in", sorted({r["move_id"][0] for r in rows})]],
                                                        ["name", "ref", "invoice_date", "partner_id"])}
        vendors = self._refs("res.partner", [m["partner_id"][0] for m in moves.values()], "ref", "V")
        mats = self._refs("product.product", [r["product_id"][0] for r in rows if r["product_id"]], "default_code", "MAT")
        out = []
        for r in rows:
            m = moves[r["move_id"][0]]
            unit = "lb"
            if r["product_id"]:
                unit = self._unit(r["product_uom_id"], f"bill {m['ref'] or m['name']}, {r['name']}")
                if unit is None:
                    continue
            out.append({"erp_id": r["id"], "write_date": r["write_date"], "invoice_no": m["ref"] or m["name"],
                        "line_no": r["id"], "invoice_date": m["invoice_date"], "supplier_ref": vendors[m["partner_id"][0]],
                        "item": r["name"], "qty": r["quantity"], "unit": unit, "unit_price": r["price_unit"],
                        "material_ref": mats.get(r["product_id"][0]) if r["product_id"] else None})
        return out
