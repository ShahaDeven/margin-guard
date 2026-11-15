"""Read sync: an ERP's changes into Margin Guard, through an ErpAdapter (adapter.py).

    python -m margin_guard.erp sync [--db PATH]

For each kind, in reference order, the adapter returns what changed since the last cursor
and each record is reconciled three ways, against its link (the ERP's values at the last
sync) and the local row:

    no local row                    added
    ERP unchanged since last sync   nothing to do
    changed in the ERP only         applied
    changed here and in the ERP     a conflict: the local row stays, and the conflict is reported
    first sync, values agree        linked
    first sync, values differ       the ERP wins, unless a person changed the row here (an
                                    approved reprice on a line, a recorded customer response
                                    on a quote): then it's a conflict

Two kinds are append-only and never overwrite anything:

    supplier price  a price the ERP has that Margin Guard doesn't becomes a price-change event,
                    the same door a supplier email comes through, so the agents work out the
                    impact and a person decides. The event key makes it idempotent: a price
                    that already arrived by email is not counted twice.
    vendor bill     new lines go through the invoice check (invoices.check_rows), so a price
                    billed above the one on file becomes a drift question, as with a CSV.

Everything runs in one transaction with the cursors, so a failed sync changes nothing and
the next one starts from the same place. What stays Margin Guard's own: a quote's margin floor
(a new quote from the ERP gets DEFAULT_FLOOR, and the report says so) and a part's conversion
cost (0 for a part the ERP introduces, also reported).
"""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from .. import db, events, invoices
from ..money import D, out
from ..parser import EventDraft, price_change_key
from .adapter import KINDS, ErpAdapter

DEFAULT_FLOOR = 0.25


class Sync:
    def __init__(self, conn: sqlite3.Connection, adapter: ErpAdapter):
        self.conn, self.a, self.system = conn, adapter, adapter.system
        self.report: dict = {k: defaultdict(int) for k in KINDS}
        self.conflicts: list[str] = []
        self.notes: list[str] = []
        self.events: list[int] = []
        self.invoice: dict | None = None
        self.bills: list[dict] = []

    # ---------------------------------------------------------------- links and cursors
    def link(self, kind: str, erp_id: int):
        return self.conn.execute("SELECT * FROM erp_links WHERE system = ? AND kind = ? AND erp_id = ?",
                                 (self.system, kind, erp_id)).fetchone()

    def save(self, kind: str, erp_id: int, local_id: str, snapshot: dict) -> None:
        self.conn.execute(
            """INSERT INTO erp_links (system, kind, erp_id, local_id, snapshot) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (system, kind, erp_id) DO UPDATE SET local_id = excluded.local_id,
               snapshot = excluded.snapshot, synced_at = datetime('now')""",
            (self.system, kind, erp_id, local_id, json.dumps(snapshot, sort_keys=True)))

    def cursor(self, kind: str) -> str | None:
        r = self.conn.execute("SELECT cursor FROM erp_cursors WHERE system = ? AND kind = ?", (self.system, kind)).fetchone()
        return r["cursor"] if r else None

    def reconcile(self, kind: str, rec: dict, view: dict, local: dict | None, protected: bool = False) -> str:
        """added | applied | unchanged | linked | conflict, following the table in the docstring."""
        link = self.link(kind, rec["erp_id"])
        before = json.loads(link["snapshot"]) if link else None
        if before is not None:
            # Compare like with like: a record can carry fewer fields than when it was last
            # synced (a won order no longer has a quote date in Odoo).
            before = {k: before.get(k) for k in view}
        if local is None:
            return "added"
        if before == view:
            return "unchanged"
        if before is not None:
            return "applied" if local == before else "conflict"
        if local == view:
            return "linked"
        return "conflict" if protected else "applied"

    # ---------------------------------------------------------------- run
    def run(self) -> dict:
        db.init_schema(self.conn)              # an older database gains the erp_* tables
        started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            for kind in KINDS:
                since = self.cursor(kind)
                records = self.a.pull(kind, since)
                handle = getattr(self, f"_{kind}")
                for rec in records:
                    handle(rec)
                if kind == "bill_line":
                    self._check_bills()
                if records:
                    newest = max(r["write_date"] for r in records)
                    # `since` is inclusive, so records written in the same second as the
                    # cursor come back next time and are recognised as unchanged.
                    self.conn.execute(
                        "INSERT INTO erp_cursors (system, kind, cursor) VALUES (?, ?, ?) "
                        "ON CONFLICT (system, kind) DO UPDATE SET cursor = excluded.cursor",
                        (self.system, kind, newest))
                self.report[kind]["pulled"] = len(records)
            self.notes += self.a.skipped()
            summary = self.summary()
            self.conn.execute("INSERT INTO erp_syncs (system, started_at, finished_at, summary) VALUES (?, ?, ?, ?)",
                              (self.system, started, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               json.dumps(summary)))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return summary

    def summary(self) -> dict:
        return {"kinds": {k: dict(v) for k, v in self.report.items()}, "conflicts": self.conflicts,
                "notes": self.notes, "events": self.events, "invoice": self.invoice}

    def count(self, kind: str, outcome: str, what: str) -> None:
        self.report[kind][outcome] += 1
        if outcome == "conflict":
            self.conflicts.append(f"{what}: changed in Margin Guard and in {self.system.capitalize()} since the last sync; "
                                  f"kept Margin Guard's")

    # ---------------------------------------------------------------- suppliers, customers, products
    def _supplier(self, r: dict) -> None:
        view = {"name": r["name"], "email_domain": r["email_domain"]}
        row = self.conn.execute("SELECT name, email_domain FROM vendors WHERE id = ?", (r["ref"],)).fetchone()
        outcome = self.reconcile("supplier", r, view, dict(row) if row else None)
        if outcome == "added":
            taken = self.conn.execute("SELECT 1 FROM vendors WHERE email_domain = ?", (r["email_domain"],)).fetchone()
            domain = f"{r['email_domain']}.{r['ref'].lower()}" if taken else r["email_domain"]
            self.conn.execute("INSERT INTO vendors (id, name, email_domain) VALUES (?, ?, ?)", (r["ref"], r["name"], domain))
        elif outcome == "applied":
            self.conn.execute("UPDATE vendors SET name = ?, email_domain = ? WHERE id = ?", (r["name"], r["email_domain"], r["ref"]))
        self._done("supplier", r, outcome, r["ref"], view, f"supplier {r['ref']}")

    CUSTOMER = ("name", "tier", "price_lock_until", "contract_note", "buyer_name", "buyer_email", "buyer_phone",
                "account_manager", "account_manager_phone")

    def _customer(self, r: dict) -> None:
        view = {k: r[k] for k in self.CUSTOMER}
        row = self.conn.execute(f"SELECT {', '.join(self.CUSTOMER)} FROM customers WHERE id = ?", (r["ref"],)).fetchone()
        local = {k: (row[k] or None) for k in self.CUSTOMER} if row else None
        outcome = self.reconcile("customer", r, view, local)
        if outcome == "added":
            self.conn.execute(f"INSERT INTO customers (id, {', '.join(self.CUSTOMER)}) VALUES (?{', ?' * len(self.CUSTOMER)})",
                              (r["ref"], *(r[k] or ("" if k.startswith(("buyer", "account")) else None) for k in self.CUSTOMER)))
        elif outcome == "applied":
            self.conn.execute(f"UPDATE customers SET {', '.join(f'{k} = ?' for k in self.CUSTOMER)} WHERE id = ?",
                              (*(r[k] or ("" if k.startswith(("buyer", "account")) else None) for k in self.CUSTOMER), r["ref"]))
        self._done("customer", r, outcome, r["ref"], view, f"customer {r['ref']}")

    def _material(self, r: dict) -> None:
        # A material's cost moves through supplier prices (events), never through this record.
        view = {"name": r["name"]}
        row = self.conn.execute("SELECT name FROM materials WHERE id = ?", (r["ref"],)).fetchone()
        outcome = self.reconcile("material", r, view, dict(row) if row else None)
        if outcome == "added":
            self.conn.execute("INSERT INTO materials (id, name, category, cost_per_lb, aliases) VALUES (?, ?, 'other', ?, '[]')",
                              (r["ref"], r["name"], out(D(str(round(r["cost_per_lb"], 6))))))
        elif outcome == "applied":
            self.conn.execute("UPDATE materials SET name = ? WHERE id = ?", (r["name"], r["ref"]))
        self._done("material", r, outcome, r["ref"], view, f"material {r['ref']}")

    def _part(self, r: dict) -> None:
        view = {"name": r["name"]}
        row = self.conn.execute("SELECT name FROM parts WHERE id = ?", (r["ref"],)).fetchone()
        outcome = self.reconcile("part", r, view, dict(row) if row else None)
        if outcome == "added":
            self.conn.execute("INSERT INTO parts (id, name, conversion_cost) VALUES (?, ?, 0)", (r["ref"], r["name"]))
            self.notes.append(f"part {r['ref']} is new from {self.system}: its conversion cost is set to 0 until someone enters it")
        elif outcome == "applied":
            self.conn.execute("UPDATE parts SET name = ? WHERE id = ?", (r["name"], r["ref"]))
        self._done("part", r, outcome, r["ref"], view, f"part {r['ref']}")

    def _done(self, kind: str, r: dict, outcome: str, local_id: str, view: dict, what: str) -> None:
        self.count(kind, outcome, what)
        if outcome != "conflict":
            self.save(kind, r["erp_id"], local_id, view)

    # ---------------------------------------------------------------- supplier prices (append-only)
    def _supplier_price(self, r: dict) -> None:
        mat, ven, cost, day = r["material_ref"], r["supplier_ref"], r["cost_per_lb"], r["effective_date"]
        view = {"cost_per_lb": cost, "effective_date": day}
        if not self.conn.execute("SELECT 1 FROM materials WHERE id = ?", (mat,)).fetchone() or \
                not self.conn.execute("SELECT 1 FROM vendors WHERE id = ?", (ven,)).fetchone():
            self.notes.append(f"{ven} price for {mat}: the material or supplier isn't in Margin Guard; skipped")
            self.report["supplier_price"]["skipped"] += 1
            return
        self._costing(mat, ven, r["is_costing"])
        link = self.link("supplier_price", r["erp_id"])
        if link and json.loads(link["snapshot"]) == view:
            self.report["supplier_price"]["unchanged"] += 1
            return
        on_file = self.conn.execute(
            "SELECT cost_per_lb FROM material_price_history WHERE material_id = ? AND vendor_id = ? AND effective_date = ? "
            "ORDER BY id DESC LIMIT 1", (mat, ven, day)).fetchone()
        if on_file and abs(on_file["cost_per_lb"] - cost) < 5e-7:
            self.report["supplier_price"]["linked"] += 1
        else:
            prev = self.conn.execute(
                "SELECT cost_per_lb FROM material_price_history WHERE material_id = ? AND vendor_id = ? AND effective_date < ? "
                "ORDER BY effective_date DESC, id DESC LIMIT 1", (mat, ven, day)).fetchone()
            old = D(prev["cost_per_lb"] if prev else self.conn.execute(
                "SELECT cost_per_lb FROM materials WHERE id = ?", (mat,)).fetchone()["cost_per_lb"])
            payload = {"material_id": mat, "vendor_id": ven, "new_cost_per_lb": cost, "effective_date": day,
                       "old_cost_per_lb": out(old), "pct_change": out(((D(str(cost)) - old) / old).quantize(D("0.000001"))) if old else None,
                       "match_method": "erp", "source": self.system, "erp_id": r["erp_id"]}
            event_id = events.append(self.conn, EventDraft("price_change.detected", price_change_key(ven, mat, cost, day), payload),
                                     source_ref=f"{self.system}:product.supplierinfo:{r['erp_id']}")
            if event_id:
                self.events.append(event_id)
                self.report["supplier_price"]["new_price"] += 1
            else:
                self.report["supplier_price"]["already_on_file"] += 1    # same change already came by email
        self.save("supplier_price", r["erp_id"], f"{mat}:{ven}:{day}", view)

    def _costing(self, mat: str, ven: str, is_costing: bool) -> None:
        row = self.conn.execute("SELECT is_primary FROM material_vendors WHERE material_id = ? AND vendor_id = ?", (mat, ven)).fetchone()
        if row is None:
            self.conn.execute("INSERT INTO material_vendors (material_id, vendor_id, is_primary) VALUES (?, ?, 0)", (mat, ven))
        if is_costing and not (row and row["is_primary"]):
            self.conn.execute("UPDATE material_vendors SET is_primary = 0 WHERE material_id = ?", (mat,))
            self.conn.execute("UPDATE material_vendors SET is_primary = 1 WHERE material_id = ? AND vendor_id = ?", (mat, ven))
            if row is not None:
                self.notes.append(f"{mat} is now costed at {ven}, as in {self.system}")

    # ---------------------------------------------------------------- BOMs
    def _bom(self, r: dict) -> None:
        part = r["part_ref"]
        view = {"lines": [[m, q] for m, q in r["lines"]]}
        if not self.conn.execute("SELECT 1 FROM parts WHERE id = ?", (part,)).fetchone():
            self.notes.append(f"BOM for {part}: the part isn't in Margin Guard; skipped")
            return
        missing = [m for m, _ in r["lines"] if not self.conn.execute("SELECT 1 FROM materials WHERE id = ?", (m,)).fetchone()]
        if missing:
            self.notes.append(f"BOM for {part}: {', '.join(missing)} isn't in Margin Guard; skipped")
            return
        rows = self.conn.execute("SELECT material_id, lb_per_unit, scrap_rate FROM part_materials WHERE part_id = ?", (part,)).fetchall()
        # Odoo's BOM line has no scrap rate: compare gross pounds per unit.
        local = {"lines": sorted([m["material_id"], round(m["lb_per_unit"] * (1 + m["scrap_rate"]), 4)] for m in rows)} if rows else None
        outcome = self.reconcile("bom", r, view, local)
        if outcome in ("added", "applied"):
            self.conn.execute("DELETE FROM part_materials WHERE part_id = ?", (part,))
            self.conn.executemany("INSERT INTO part_materials (part_id, material_id, lb_per_unit, scrap_rate) VALUES (?, ?, ?, 0)",
                                  [(part, m, q) for m, q in r["lines"]])
        self._done("bom", r, outcome, part, view, f"BOM for {part}")

    # ---------------------------------------------------------------- quotes and lines
    QUOTE = ("customer_ref", "status", "issued_date", "valid_until", "ordered_date")

    def _quote(self, r: dict) -> None:
        q = r["ref"]
        # An ERP that can't say when a won order was quoted (Odoo can't) leaves the date out of
        # the comparison, and Margin Guard's own date stands.
        fields = [k for k in self.QUOTE if not (k == "issued_date" and r[k] is None)]
        view = {k: r[k] for k in fields}
        row = self.conn.execute("SELECT customer_id, status, issued_date, valid_until, ordered_date FROM quotes WHERE id = ?", (q,)).fetchone()
        if not self.conn.execute("SELECT 1 FROM customers WHERE id = ?", (r["customer_ref"],)).fetchone():
            self.notes.append(f"quote {q}: customer {r['customer_ref']} isn't in Margin Guard; skipped")
            return
        local = None
        if row:
            local = {"customer_ref": row["customer_id"], "status": row["status"], "issued_date": row["issued_date"],
                     "valid_until": row["valid_until"], "ordered_date": row["ordered_date"]}
            if local["status"] == "expired":
                local["status"] = "lost"
            local = {k: local[k] for k in fields}
        responded = bool(self.conn.execute("SELECT 1 FROM quote_outcomes WHERE quote_id = ?", (q,)).fetchone())
        outcome = self.reconcile("quote", r, view, local, protected=responded)
        if outcome == "added":
            self.conn.execute("INSERT INTO quotes (id, customer_id, status, issued_date, valid_until, margin_floor, ordered_date) "
                              "VALUES (?, ?, ?, ?, ?, ?, ?)",
                              (q, r["customer_ref"], r["status"], r["issued_date"] or r["ordered_date"], r["valid_until"],
                               DEFAULT_FLOOR, r["ordered_date"]))
            self.notes.append(f"quote {q} is new from {self.system}: margin floor set to {DEFAULT_FLOOR:.0%}; change it in Margin Guard"
                              + ("" if r["issued_date"] else "; quoted date unknown, set to the order date"))
        elif outcome == "applied":
            self.conn.execute("UPDATE quotes SET customer_id = ?, status = ?, issued_date = COALESCE(?, issued_date), "
                              "valid_until = ?, ordered_date = ? WHERE id = ?",
                              (r["customer_ref"], r["status"], r["issued_date"], r["valid_until"], r["ordered_date"], q))
        self._done("quote", r, outcome, q, view, f"quote {q}")
        if outcome != "conflict":
            self._lines(q, r["lines"])

    def _lines(self, q: str, lines: list[dict]) -> None:
        local_rows = self.conn.execute("SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY id", (q,)).fetchall()
        linked = {int(l["local_id"]): l for l in self.conn.execute(
            "SELECT * FROM erp_links WHERE system = ? AND kind = 'quote_line' AND local_id IN (%s)" % ",".join("?" * len(local_rows)),
            (self.system, *[str(r["id"]) for r in local_rows])).fetchall()} if local_rows else {}
        # First sync: pair unlinked local lines with ERP lines in order, part by part.
        free = [r for r in local_rows if r["id"] not in linked]
        seen = set()
        for ln in lines:
            link = self.link("quote_line", ln["erp_id"])
            if link:
                local = next((r for r in local_rows if r["id"] == int(link["local_id"])), None)
            else:
                local = next((r for r in free if r["part_id"] == ln["part_ref"]), None)
                if local is not None:
                    free.remove(local)
            view = {"part_ref": ln["part_ref"], "qty": ln["qty"], "unit_price": round(ln["unit_price"], 6)}
            lv = {"part_ref": local["part_id"], "qty": local["qty"], "unit_price": round(local["unit_price"], 6)} if local else None
            revised = bool(local and self.conn.execute("SELECT 1 FROM quote_revisions WHERE line_id = ?", (local["id"],)).fetchone())
            outcome = self.reconcile("quote_line", ln, view, lv, protected=revised)
            if outcome == "added":
                conv = self.conn.execute("SELECT conversion_cost FROM parts WHERE id = ?", (ln["part_ref"],)).fetchone()
                conversion = D(conv["conversion_cost"]) if conv else D(0)
                basis = max(D(str(ln["cost_each"] or 0)) - conversion, D(0))
                cur = self.conn.execute("INSERT INTO quote_lines (quote_id, part_id, qty, unit_price, material_cost_basis, conversion_cost) "
                                        "VALUES (?, ?, ?, ?, ?, ?)",
                                        (q, ln["part_ref"], int(ln["qty"]), ln["unit_price"], out(basis), out(conversion)))
                local_id = cur.lastrowid
            else:
                local_id = local["id"]
                if outcome == "applied":
                    self.conn.execute("UPDATE quote_lines SET part_id = ?, qty = ?, unit_price = ? WHERE id = ?",
                                      (ln["part_ref"], int(ln["qty"]), ln["unit_price"], local_id))
            seen.add(local_id)
            self.report["quote"][f"line_{outcome}"] += 1
            if outcome == "conflict":
                self.conflicts.append(f"quote {q}, {ln['part_ref']}: price or quantity changed in Margin Guard (an approved "
                                      f"reprice) and in {self.system.capitalize()}; kept Margin Guard's")
            else:
                self.save("quote_line", ln["erp_id"], str(local_id), view)
        # A line linked before but gone from the ERP quote was removed there.
        for local_id, link in linked.items():
            if local_id in seen:
                continue
            if self.conn.execute("SELECT 1 FROM quote_revisions WHERE line_id = ?", (local_id,)).fetchone():
                self.conflicts.append(f"quote {q}: a line removed in {self.system.capitalize()} has an approved reprice here; kept it")
                continue
            self.conn.execute("DELETE FROM quote_lines WHERE id = ?", (local_id,))
            self.conn.execute("DELETE FROM erp_links WHERE system = ? AND kind = 'quote_line' AND erp_id = ?", (self.system, link["erp_id"]))
            self.report["quote"]["line_removed"] += 1

    # ---------------------------------------------------------------- vendor bills (append-only)
    def _bill_line(self, r: dict) -> None:
        if self.link("bill_line", r["erp_id"]):
            self.report["bill_line"]["unchanged"] += 1
            return
        if not self.conn.execute("SELECT 1 FROM vendors WHERE id = ?", (r["supplier_ref"],)).fetchone():
            self.notes.append(f"bill {r['invoice_no']}: supplier {r['supplier_ref']} isn't in Margin Guard; skipped")
            return
        self.bills.append(r)

    def _check_bills(self) -> None:
        bills, self.bills = self.bills, []
        if not bills:
            return
        rows = [{"_row": i, "invoice_no": b["invoice_no"], "line_no": int(b["line_no"]), "invoice_date": b["invoice_date"],
                 "vendor_id": b["supplier_ref"], "item": b["item"], "qty": b["qty"], "unit": b["unit"],
                 "unit_price": b["unit_price"], "pack_qty": None} for i, b in enumerate(bills, start=1)]
        # A line the ERP links to a product is judged against that material, not guessed from its text.
        overrides = {(b["supplier_ref"], b["item"].strip().lower()): b["material_ref"] for b in bills if b.get("material_ref")}
        rep = invoices.check_rows(self.conn, rows, source=self.system, overrides=overrides, commit=False)
        self.invoice = {k: rep[k] for k in ("lines", "at_price", "above", "below", "already_on_file", "overpaid_usd")} | {
            "drifts": len(rep["drifts"]), "not_judged": len(rep["not_judged"])}
        for b in bills:
            self.save("bill_line", b["erp_id"], f"{b['invoice_no']}/{b['line_no']}", {"unit_price": b["unit_price"], "qty": b["qty"]})
        self.report["bill_line"]["added"] += len(bills)


def sync(conn: sqlite3.Connection, adapter: ErpAdapter) -> dict:
    return Sync(conn, adapter).run()


def report_text(s: dict, system: str = "odoo") -> str:
    name = system.capitalize()
    lines = [f"Synced from {name}:"]
    for kind, c in s["kinds"].items():
        parts = [f"{v} {k.replace('_', ' ')}" for k, v in sorted(c.items()) if v and k != "pulled"]
        lines.append(f"  {kind.replace('_', ' '):15} {c.get('pulled', 0):4} changed in {name}" + (f": {', '.join(parts)}" if parts else ""))
    if s["events"]:
        lines.append(f"\n{len(s['events'])} new supplier price(s) from {name} are queued as price changes: "
                     f"run `python -m margin_guard.coordinator` (or the console's agents) to work out the impact.")
    if s["invoice"]:
        i = s["invoice"]
        lines.append(f"\nVendor bills: {i['lines']} new lines, {i['above']} billed above the price on file "
                     f"(${i['overpaid_usd']:,.2f} over), {i['drifts']} drift question(s).")
    for title, items in (("Conflicts (kept Margin Guard's)", s["conflicts"]), ("Notes", s["notes"])):
        if items:
            lines.append(f"\n{title}:")
            lines += [f"  - {x}" for x in items[:40]] + ([f"  ... and {len(items) - 40} more"] if len(items) > 40 else [])
    return "\n".join(lines)
