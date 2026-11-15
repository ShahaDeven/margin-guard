"""Send queued writes (outbox.py) to Odoo, each checked against what Odoo holds first.

    python -m margin_guard.erp push [--db PATH] [--force ID]

    quote_prices    the quotation must still be a quotation (draft or sent), and every line must
                    still hold the price Margin Guard last saw; then each line takes its approved
                    price and the quotation gets a note saying why
    call_task       a Call activity on the quotation for its salesperson (the account manager),
                    unless an identical one is already there
    supplier_price  a dated vendor price line in pounds; the open line before it is closed the
                    day before, so Odoo never holds two prices for one day. If Odoo already has
                    a different price for that date, it stops.

Every write is idempotent: if a retry finds the change already in Odoo (a write that landed
before its response was lost), it is marked sent, not done twice. A write Odoo would make wrong
stops as a conflict and becomes a question in To decide; `--force ID` writes it anyway once a
person has looked. A write that fails for any other reason (Odoo down) stays queued.
"""

import html
import json
import sqlite3
from datetime import date, timedelta

from .. import events
from ..parser import EventDraft
from .odoo import OdooClient, OdooError
from .outbox import SYSTEM

EPS = 5e-7


class Conflict(Exception):
    """Odoo no longer holds what the write expects."""


class Writer:
    def __init__(self, conn: sqlite3.Connection, client: OdooClient):
        self.conn, self.c = conn, client

    # ---------------------------------------------------------------- lookups
    def erp_id(self, kind: str, local_id: str) -> int | None:
        r = self.conn.execute("SELECT erp_id FROM erp_links WHERE system = ? AND kind = ? AND local_id = ?",
                              (SYSTEM, kind, local_id)).fetchone()
        return r["erp_id"] if r else None

    def order(self, quote_id: str) -> dict:
        oid = self.erp_id("quote", quote_id)
        rows = self.c.search_read("sale.order", [["id", "=", oid]] if oid else [["name", "=", quote_id]],
                                  ["name", "state", "user_id", "order_line"])
        if not rows:
            raise OdooError(f"quote {quote_id} isn't in Odoo")
        return rows[0]

    def relink(self, kind: str, erp_id: int, local_id: str, snapshot: dict) -> None:
        """Record what Odoo now holds, so the next sync sees this write as already known."""
        self.conn.execute(
            """INSERT INTO erp_links (system, kind, erp_id, local_id, snapshot) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (system, kind, erp_id) DO UPDATE SET snapshot = excluded.snapshot, synced_at = datetime('now')""",
            (SYSTEM, kind, erp_id, local_id, json.dumps(snapshot, sort_keys=True)))

    # ---------------------------------------------------------------- the three writes
    def quote_prices(self, p: dict, force: bool) -> str:
        o = self.order(p["quote_id"])
        if o["state"] not in ("draft", "sent") and not force:
            raise Conflict(f"quote {p['quote_id']} is no longer a quotation in Odoo ({o['state']}); its prices can't be revised there")
        targets = []
        for ln in p["lines"]:
            lid = self.erp_id("quote_line", str(ln["line_id"]))
            if lid is None:
                raise Conflict(f"quote {p['quote_id']}: a line here has no matching line in Odoo")
            targets.append((ln, lid))
        current = {r["id"]: r for r in self.c.search_read("sale.order.line", [["id", "in", [t[1] for t in targets]]],
                                                          ["price_unit", "product_uom_qty", "product_id"])}
        todo = []
        for ln, lid in targets:
            now = current[lid]["price_unit"]
            if abs(now - ln["new"]) < EPS:
                continue                                  # already there: a retry after a lost response
            if abs(now - ln["old"]) >= EPS and not force:
                raise Conflict(f"quote {p['quote_id']}: a line in Odoo is ${now:.4f}, not the ${ln['old']:.4f} Margin Guard "
                               f"revised from; someone changed it there")
            todo.append((ln, lid))
        names = dict(self.conn.execute("SELECT ql.id, p.name FROM quote_lines ql JOIN parts p ON p.id = ql.part_id "
                                       "WHERE ql.quote_id = ?", (p["quote_id"],)).fetchall())
        for ln, lid in todo:
            self.c.write("sale.order.line", [lid], {"price_unit": ln["new"]})
        if todo:
            items = "".join(f"<li>{html.escape(names.get(ln['line_id'], 'line'))}: ${ln['old']:.4f} → ${ln['new']:.4f}</li>"
                            for ln, _ in todo)
            # Odoo escapes a body it isn't told is HTML; every value in it is escaped above.
            self.c.call("sale.order", "message_post", ids=[o["id"]], message_type="comment", subtype_xmlid="mail.mt_note",
                        body=f"<p>{html.escape(p['note'])}</p><ul>{items}</ul>", body_is_html=True)
        for ln, lid in targets:
            row = self.conn.execute("SELECT part_id, qty FROM quote_lines WHERE id = ?", (ln["line_id"],)).fetchone()
            if row:
                self.relink("quote_line", lid, str(ln["line_id"]),
                            {"part_ref": row["part_id"], "qty": row["qty"], "unit_price": round(ln["new"], 6)})
        return f"{o['name']}: {len(todo)} line price(s) written" if todo else f"{o['name']}: prices were already in Odoo"

    def call_task(self, p: dict, force: bool) -> str:
        o = self.order(p["quote_id"])
        found = self.c.search_read("mail.activity", [["res_model", "=", "sale.order"], ["res_id", "=", o["id"]],
                                                     ["summary", "=", p["summary"]]], ["id"])
        if found:
            return f"{o['name']}: the call activity was already in Odoo"
        model = self.c.search_read("ir.model", [["model", "=", "sale.order"]], ["id"])[0]["id"]
        who = " ".join(filter(None, [f"Call {p['buyer']}" if p.get("buyer") else "Call the buyer", p.get("phone")]))
        note = f"<p>{html.escape(who)}</p>" + "".join(f"<p>{html.escape(x)}</p>" for x in (p.get("note") or "").split("\n\n") if x.strip())
        aid = self.c.create("mail.activity", [{
            "res_model_id": model, "res_id": o["id"], "activity_type_id": self.c.xmlid("mail", "mail_activity_data_call"),
            "summary": p["summary"], "note": note, "user_id": o["user_id"][0] if o["user_id"] else False,
            "date_deadline": (date.today() + timedelta(days=1)).isoformat()}])[0]
        return f"{o['name']}: call activity #{aid} for {o['user_id'][1] if o['user_id'] else 'no salesperson'}"

    def supplier_price(self, p: dict, force: bool) -> str:
        mat, ven, cost, day = p["material_id"], p["vendor_id"], float(p["cost_per_lb"]), p["effective_date"]
        partner = self.erp_id("supplier", ven) or next(iter(
            r["id"] for r in self.c.search_read("res.partner", [["ref", "=", ven]], ["id"])), None)
        product = self.erp_id("material", mat) or next(iter(
            r["id"] for r in self.c.search_read("product.product", [["default_code", "=", mat]], ["id"])), None)
        if not partner or not product:
            raise OdooError(f"{ven} or {mat} isn't in Odoo")
        tmpl = self.c.search_read("product.product", [["id", "=", product]], ["product_tmpl_id"])[0]["product_tmpl_id"][0]
        lines = self.c.search_read("product.supplierinfo", [["partner_id", "=", partner], ["product_tmpl_id", "=", tmpl],
                                                            ["min_qty", "=", 0]], ["price", "date_start", "date_end", "sequence"])
        same = [ln for ln in lines if ln["date_start"] == day]
        if same:
            if abs(same[0]["price"] - cost) < EPS:
                self.relink("supplier_price", same[0]["id"], f"{mat}:{ven}:{day}", {"cost_per_lb": cost, "effective_date": day})
                return f"{ven} {mat}: ${cost}/lb from {day} was already in Odoo"
            if not force:
                raise Conflict(f"Odoo already has {ven}'s price for {mat} from {day} at ${same[0]['price']}/lb, not ${cost}/lb")
            self.c.write("product.supplierinfo", [same[0]["id"]], {"price": cost})
            self.relink("supplier_price", same[0]["id"], f"{mat}:{ven}:{day}", {"cost_per_lb": cost, "effective_date": day})
            return f"{ven} {mat}: price from {day} overwritten to ${cost}/lb"
        start = date.fromisoformat(day)
        before = [ln for ln in lines if ln["date_start"] and ln["date_start"] < day]
        after = sorted(ln["date_start"] for ln in lines if ln["date_start"] and ln["date_start"] > day)
        prev = max(before, key=lambda ln: ln["date_start"]) if before else None
        if prev and (not prev["date_end"] or prev["date_end"] >= day):
            self.c.write("product.supplierinfo", [prev["id"]], {"date_end": (start - timedelta(days=1)).isoformat()})
        costing = self.conn.execute("SELECT is_primary FROM material_vendors WHERE material_id = ? AND vendor_id = ?", (mat, ven)).fetchone()
        new = self.c.create("product.supplierinfo", [{
            "partner_id": partner, "product_tmpl_id": tmpl, "product_uom_id": self.c.xmlid("uom", "product_uom_lb"),
            "price": cost, "min_qty": 0, "date_start": day,
            "date_end": (date.fromisoformat(after[0]) - timedelta(days=1)).isoformat() if after else False,
            "sequence": prev["sequence"] if prev else (1 if costing and costing["is_primary"] else 10)}])[0]
        self.relink("supplier_price", new, f"{mat}:{ven}:{day}", {"cost_per_lb": cost, "effective_date": day})
        return f"{ven} {mat}: ${cost}/lb from {day} (supplierinfo #{new})"

    # ---------------------------------------------------------------- run
    def send(self, item: sqlite3.Row, force: bool = False) -> str:
        p = json.loads(item["payload"])
        try:
            detail = getattr(self, item["kind"])(p, force)
        except Conflict as exc:
            self.conn.execute("UPDATE erp_outbox SET status = 'conflict', detail = ? WHERE id = ?", (str(exc), item["id"]))
            self.question(item, p, str(exc))
            self.conn.commit()
            return "conflict"
        except OdooError as exc:
            self.conn.execute("UPDATE erp_outbox SET status = 'failed', detail = ? WHERE id = ?", (str(exc), item["id"]))
            self.conn.commit()
            return "failed"
        self.conn.execute("UPDATE erp_outbox SET status = 'sent', detail = ?, sent_at = datetime('now') WHERE id = ?",
                          (detail, item["id"]))
        if force:
            # A person looked at the conflict and wrote it anyway: the question is answered.
            self.conn.execute(
                "UPDATE proposals SET status = 'approved', final_action = 'resolve_event', reviewer_note = 'Written to Odoo anyway', "
                "reviewed_at = datetime('now') WHERE status = 'pending' AND event_id IN "
                "(SELECT id FROM events WHERE idempotency_key = ?)", (f"erp_conflict:{item['id']}",))
        self.conn.commit()
        return "sent"

    def question(self, item: sqlite3.Row, p: dict, reason: str) -> None:
        """A refused write goes in front of a person in To decide, like any other doubt."""
        what = {"quote_prices": "revised prices", "call_task": "call task", "supplier_price": "supplier price"}[item["kind"]]
        facts = {"kind": "erp_conflict", "email_id": None, "vendor_id": p.get("vendor_id"), "outbox_id": item["id"],
                 "write": item["kind"], "quote_id": p.get("quote_id"), "material_id": p.get("material_id"),
                 "review_reasons": [reason], "summary": f"Odoo refused the {what}"}
        ev = events.append(self.conn, EventDraft("erp.write_conflict", f"erp_conflict:{item['id']}", facts),
                           source_ref=f"{SYSTEM}:outbox:{item['id']}")
        if ev is None:
            return
        self.conn.execute("UPDATE events SET status = 'processed' WHERE id = ?", (ev,))
        self.conn.execute(
            "INSERT INTO proposals (idempotency_key, event_id, quote_id, kind, action, decided_by, rule_id, rationale, facts, exposure_usd) "
            "VALUES (?, ?, ?, 'event_review', 'resolve_event', 'rule', 'erp_conflict', ?, ?, 0)",
            (f"{ev}:event", ev, p.get("quote_id"), f"Odoo write needs a person: {reason}", json.dumps(facts)))


def push(conn: sqlite3.Connection, client: OdooClient, force_id: int | None = None) -> dict:
    w = Writer(conn, client)
    if force_id is not None:
        item = conn.execute("SELECT * FROM erp_outbox WHERE id = ?", (force_id,)).fetchone()
        if item is None:
            raise OdooError(f"no queued write #{force_id}")
        items = [item]
    else:
        items = conn.execute("SELECT * FROM erp_outbox WHERE status IN ('pending', 'failed') ORDER BY id").fetchall()
    result: dict = {"sent": [], "conflict": [], "failed": []}
    for item in items:
        status = w.send(item, force=force_id is not None)
        row = conn.execute("SELECT detail FROM erp_outbox WHERE id = ?", (item["id"],)).fetchone()
        result[status].append(f"#{item['id']} {item['kind']}: {row['detail']}")
    return result
