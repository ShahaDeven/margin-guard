"""Read sync from an ERP: the engine against a fake adapter that mirrors the seeded shop, and
the Odoo adapter's mapping against a fake Odoo. No Docker, no network."""

import json
from itertools import count

import pytest

from margin_guard import events
from margin_guard.erp import sync as erp_sync
from margin_guard.erp.odoo_adapter import OdooAdapter
from margin_guard.erp.sync import DEFAULT_FLOOR, sync
from margin_guard.parser import EventDraft, price_change_key

T0, T1 = "2026-11-14 10:00:00", "2026-11-14 11:00:00"


class MirrorAdapter:
    """An ERP that holds exactly what the seeded shop holds, editable per test."""
    system = "odoo"

    def __init__(self, conn):
        ids = count(1)
        q = lambda sql: conn.execute(sql).fetchall()  # noqa: E731
        primary = {(r["material_id"], r["vendor_id"]): r["is_primary"] for r in q("SELECT * FROM material_vendors")}
        lines = {}
        for ln in q("SELECT * FROM quote_lines ORDER BY id"):
            lines.setdefault(ln["quote_id"], []).append({"erp_id": next(ids), "part_ref": ln["part_id"], "qty": ln["qty"],
                                                         "unit_price": ln["unit_price"],
                                                         "cost_each": ln["material_cost_basis"] + ln["conversion_cost"]})
        bom = {}
        for r in q("SELECT * FROM part_materials ORDER BY material_id"):
            bom.setdefault(r["part_id"], []).append((r["material_id"], round(r["lb_per_unit"] * (1 + r["scrap_rate"]), 4)))
        stamp = lambda d: {"erp_id": next(ids), "write_date": T0} | d  # noqa: E731
        self.records = {
            "supplier": [stamp({"ref": v["id"], "name": v["name"], "email_domain": v["email_domain"]}) for v in q("SELECT * FROM vendors")],
            "customer": [stamp({"ref": c["id"], **{k: c[k] or None for k in erp_sync.Sync.CUSTOMER}}) for c in q("SELECT * FROM customers")],
            "material": [stamp({"ref": m["id"], "name": m["name"], "cost_per_lb": m["cost_per_lb"]}) for m in q("SELECT * FROM materials")],
            "part": [stamp({"ref": p["id"], "name": p["name"]}) for p in q("SELECT * FROM parts")],
            "supplier_price": [stamp({"material_ref": h["material_id"], "supplier_ref": h["vendor_id"], "cost_per_lb": h["cost_per_lb"],
                                      "effective_date": h["effective_date"], "is_costing": bool(primary.get((h["material_id"], h["vendor_id"])))})
                               for h in q("SELECT * FROM material_price_history WHERE vendor_id IS NOT NULL")],
            "bom": [stamp({"part_ref": p, "lines": sorted(ls)}) for p, ls in bom.items()],
            "quote": [stamp({"ref": x["id"], "customer_ref": x["customer_id"], "status": "lost" if x["status"] == "expired" else x["status"],
                             "issued_date": None if x["status"] == "won" else x["issued_date"], "valid_until": x["valid_until"],
                             "ordered_date": x["ordered_date"], "lines": lines.get(x["id"], [])}) for x in q("SELECT * FROM quotes")],
            "bill_line": [],
        }
        self.fail_on = None

    def pull(self, kind, since):
        if kind == self.fail_on:
            raise RuntimeError("Odoo went away")
        return [r for r in self.records[kind] if since is None or r["write_date"] >= since]

    def skipped(self):
        return []

    def find(self, kind, **match):
        return next(r for r in self.records[kind] if all(r.get(k) == v for k, v in match.items()))


@pytest.fixture
def erp(conn):
    return MirrorAdapter(conn)


def _counts(conn):
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("events", "quote_lines", "quotes", "erp_links")}


# ------------------------------------------------------------------ the three-way rules


def test_first_sync_of_a_matching_shop_only_links(conn, erp):
    before = _counts(conn)
    s = sync(conn, erp)
    k = s["kinds"]
    assert k["quote"]["linked"] == 270 and k["quote"]["line_linked"] == 540
    assert k["supplier_price"]["linked"] == len(erp.records["supplier_price"])
    assert not s["conflicts"] and not s["events"]
    after = _counts(conn)
    assert after["events"] == before["events"] and after["quote_lines"] == before["quote_lines"]


def test_second_sync_finds_nothing_new(conn, erp):
    sync(conn, erp)
    s = sync(conn, erp)              # the cursor is inclusive: records come back and are recognised
    assert all(set(c) <= {"pulled", "unchanged", "line_unchanged"} for c in s["kinds"].values())


def test_a_change_in_the_erp_is_applied(conn, erp):
    sync(conn, erp)
    line = erp.find("quote", ref="Q-2026-0101")["lines"][0]
    q = erp.find("quote", ref="Q-2026-0101")
    q["write_date"], line["unit_price"] = T1, 99.5
    s = sync(conn, erp)
    assert s["kinds"]["quote"]["line_applied"] == 1
    assert conn.execute("SELECT unit_price FROM quote_lines WHERE quote_id = 'Q-2026-0101' ORDER BY id").fetchone()[0] == 99.5


def test_a_change_on_both_sides_is_a_conflict_and_keeps_ours(conn, erp):
    sync(conn, erp)
    conn.execute("UPDATE customers SET buyer_phone = '(312) 555-9999' WHERE id = 'C-01'")
    c = erp.find("customer", ref="C-01")
    c["write_date"], c["buyer_phone"] = T1, "(312) 555-0000"
    s = sync(conn, erp)
    assert s["kinds"]["customer"]["conflict"] == 1 and "customer C-01" in s["conflicts"][0]
    assert conn.execute("SELECT buyer_phone FROM customers WHERE id = 'C-01'").fetchone()[0] == "(312) 555-9999"


def test_an_approved_reprice_is_never_overwritten_on_first_sync(conn, erp):
    line = conn.execute("SELECT * FROM quote_lines WHERE quote_id = 'Q-2026-0101' ORDER BY id").fetchone()
    conn.execute("UPDATE quote_lines SET unit_price = unit_price + 1 WHERE id = ?", (line["id"],))
    conn.execute("INSERT INTO proposals (idempotency_key, event_id, quote_id, kind, action, decided_by, rationale, facts) "
                 "VALUES ('x', 1, 'Q-2026-0101', 'quote_action', 'reprice', 'llm', 'r', '{}')")
    conn.execute("INSERT INTO events (event_type, idempotency_key, payload) VALUES ('t', 'k-x', '{}')")
    conn.execute("INSERT INTO quote_revisions (quote_id, line_id, proposal_id, old_price, new_price) VALUES (?, ?, 1, ?, ?)",
                 ("Q-2026-0101", line["id"], line["unit_price"], line["unit_price"] + 1))
    s = sync(conn, erp)
    assert s["kinds"]["quote"]["line_conflict"] == 1
    assert conn.execute("SELECT unit_price FROM quote_lines WHERE id = ?", (line["id"],)).fetchone()[0] == line["unit_price"] + 1


# ------------------------------------------------------------------ supplier prices become price changes


def test_a_new_supplier_price_becomes_a_price_change_event(conn, erp):
    sync(conn, erp)
    erp.records["supplier_price"].append({"erp_id": 9001, "write_date": T1, "material_ref": "MAT-EPDM-70", "supplier_ref": "V-MWP",
                                          "cost_per_lb": 2.35, "effective_date": "2026-12-01", "is_costing": True})
    s = sync(conn, erp)
    assert len(s["events"]) == 1 and s["kinds"]["supplier_price"]["new_price"] == 1
    e = conn.execute("SELECT * FROM events WHERE id = ?", (s["events"][0],)).fetchone()
    p = json.loads(e["payload"])
    assert e["event_type"] == "price_change.detected" and e["source_ref"] == "odoo:product.supplierinfo:9001"
    assert (p["old_cost_per_lb"], p["new_cost_per_lb"], p["effective_date"]) == (2.1, 2.35, "2026-12-01")
    assert p["pct_change"] == pytest.approx(0.119048, abs=1e-6)


def test_a_price_that_already_came_by_email_is_not_counted_twice(conn, erp):
    sync(conn, erp)
    events.append(conn, EventDraft("price_change.detected", price_change_key("V-MWP", "MAT-EPDM-70", 2.35, "2026-12-01"), {}), "email")
    erp.records["supplier_price"].append({"erp_id": 9002, "write_date": T1, "material_ref": "MAT-EPDM-70", "supplier_ref": "V-MWP",
                                          "cost_per_lb": 2.35, "effective_date": "2026-12-01", "is_costing": True})
    s = sync(conn, erp)
    assert not s["events"] and s["kinds"]["supplier_price"]["already_on_file"] == 1


def test_the_costing_supplier_follows_the_erp(conn, erp):
    sync(conn, erp)
    alt = conn.execute("SELECT material_id, vendor_id FROM material_vendors WHERE is_primary = 0 LIMIT 1").fetchone()
    erp.records["supplier_price"].append({"erp_id": 9003, "write_date": T1, "material_ref": alt["material_id"],
                                          "supplier_ref": alt["vendor_id"], "cost_per_lb": 3.0, "effective_date": "2026-12-01",
                                          "is_costing": True})
    s = sync(conn, erp)
    assert conn.execute("SELECT vendor_id FROM material_vendors WHERE material_id = ? AND is_primary = 1",
                        (alt["material_id"],)).fetchone()[0] == alt["vendor_id"]
    assert any("now costed at" in n for n in s["notes"])


# ------------------------------------------------------------------ quotes


def test_a_quote_won_in_the_erp_keeps_our_quote_date(conn, erp):
    sync(conn, erp)
    q = erp.find("quote", ref="Q-2026-0101")
    q.update(write_date=T1, status="won", issued_date=None, ordered_date="2026-11-14")   # Odoo forgets the quote date
    sync(conn, erp)
    row = conn.execute("SELECT status, issued_date, ordered_date FROM quotes WHERE id = 'Q-2026-0101'").fetchone()
    assert tuple(row) == ("won", "2026-10-13", "2026-11-14")


def test_a_new_quote_from_the_erp_gets_the_default_floor(conn, erp):
    sync(conn, erp)
    erp.records["quote"].append({"erp_id": 9100, "write_date": T1, "ref": "S00999", "customer_ref": "C-01", "status": "open",
                                 "issued_date": "2026-11-14", "valid_until": "2026-12-14", "ordered_date": None,
                                 "lines": [{"erp_id": 9101, "part_ref": "P-1001", "qty": 500, "unit_price": 3.5, "cost_each": 2.6}]})
    s = sync(conn, erp)
    assert conn.execute("SELECT margin_floor FROM quotes WHERE id = 'S00999'").fetchone()[0] == DEFAULT_FLOOR
    line = conn.execute("SELECT * FROM quote_lines WHERE quote_id = 'S00999'").fetchone()
    assert line["material_cost_basis"] + line["conversion_cost"] == pytest.approx(2.6)
    assert any("S00999" in n and "margin floor" in n for n in s["notes"])


# ------------------------------------------------------------------ vendor bills and safety


def test_vendor_bills_go_through_the_invoice_check(conn, erp):
    erp.records["bill_line"] = [
        {"erp_id": 7001, "write_date": T0, "invoice_no": "INV-RC-1", "line_no": 7001, "invoice_date": "2026-10-02",
         "supplier_ref": "V-RCB", "item": "N550 carbon black", "qty": 4000, "unit": "lb", "unit_price": 1.14, "material_ref": "MAT-CB-N550"},
        {"erp_id": 7002, "write_date": T0, "invoice_no": "INV-RC-1", "line_no": 7002, "invoice_date": "2026-10-02",
         "supplier_ref": "V-RCB", "item": "Freight surcharge", "qty": 1, "unit": "lb", "unit_price": 85.0, "material_ref": None}]
    s = sync(conn, erp)
    assert s["invoice"]["above"] == 1 and s["invoice"]["drifts"] == 1 and s["invoice"]["not_judged"] == 1
    assert s["invoice"]["overpaid_usd"] == pytest.approx(200.0)
    assert sync(conn, erp)["kinds"]["bill_line"]["unchanged"] == 2         # never checked twice


def test_a_failed_sync_changes_nothing(conn, erp):
    erp.fail_on = "quote"
    with pytest.raises(RuntimeError):
        sync(conn, erp)
    assert conn.execute("SELECT COUNT(*) FROM erp_links").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM erp_cursors").fetchone()[0] == 0


# ------------------------------------------------------------------ the Odoo adapter's mapping


class FakeOdoo:
    def __init__(self, data):
        self.data = data

    def search_read(self, model, domain, fields, **kw):
        rows = self.data.get(model, [])
        for d in domain:
            if d[0] == "id" and d[1] == "in":
                rows = [r for r in rows if r["id"] in d[2]]
        return [dict(r) for r in rows]


def _odoo_prices(*lines):
    return OdooAdapter(FakeOdoo({
        "product.supplierinfo": list(lines),
        "product.template": [{"id": 5, "default_code": "MAT-NBR-70"}],
        "res.partner": [{"id": 1, "ref": "V-GLE"}, {"id": 2, "ref": "V-KRD"}],
    }))


def _price(id_, partner, price, *, seq=1, uom="lb", currency="USD", min_qty=0):
    return {"id": id_, "write_date": T0, "partner_id": [partner, "x"], "product_tmpl_id": [5, "NBR"], "price": price,
            "date_start": "2026-11-20", "min_qty": min_qty, "sequence": seq, "currency_id": [1, currency],
            "product_uom_id": [9, uom]}


def test_a_kilogram_price_becomes_dollars_per_pound():
    a = _odoo_prices(_price(1, 1, 5.10, uom="kg"))
    [p] = a.pull("supplier_price", None)
    assert p["cost_per_lb"] == pytest.approx(5.10 * 0.45359237, abs=1e-6)


def test_foreign_currency_breaks_and_strange_units_are_reported_not_guessed():
    a = _odoo_prices(_price(1, 1, 2.0, currency="EUR"), _price(2, 1, 2.0, min_qty=5000), _price(3, 1, 2.0, uom="oz"),
                     _price(4, 1, 2.25))
    got = a.pull("supplier_price", None)
    assert [p["cost_per_lb"] for p in got] == [2.25]
    notes = " ".join(a.skipped())
    assert "EUR" in notes and "break at 5000+" in notes and "'oz'" in notes


def test_the_costing_supplier_is_the_lowest_sequence():
    a = _odoo_prices(_price(1, 1, 2.25, seq=10), _price(2, 2, 2.30, seq=1))
    got = {p["supplier_ref"]: p["is_costing"] for p in a.pull("supplier_price", None)}
    assert got == {"V-GLE": False, "V-KRD": True}


def test_quote_states_and_the_won_order_date():
    a = OdooAdapter(FakeOdoo({
        "sale.order": [{"id": 1, "write_date": T0, "name": "Q-1", "partner_id": [3, "c"], "state": "sale",
                        "date_order": "2026-11-14 09:12:00", "validity_date": "2026-12-01"},
                       {"id": 2, "write_date": T0, "name": "Q-2", "partner_id": [3, "c"], "state": "sent",
                        "date_order": "2026-10-01 08:00:00", "validity_date": False}],
        "sale.order.line": [], "product.product": [], "res.partner": [{"id": 3, "ref": "C-01"}],
    }))
    won, open_ = a.pull("quote", None)
    assert (won["status"], won["issued_date"], won["ordered_date"]) == ("won", None, "2026-11-14")
    assert (open_["status"], open_["issued_date"], open_["valid_until"]) == ("open", "2026-10-01", "2026-10-01")


# ------------------------------------------------------------------ the trace: what each sync changed, and where


def test_a_first_sync_that_only_links_records_no_changes(conn, erp):
    s = sync(conn, erp)
    assert s["changes"] == [] and s["changes_cut"] == 0


def test_a_line_price_change_is_traced_to_the_quote_with_its_margin(conn, erp):
    sync(conn, erp)
    q = erp.find("quote", ref="Q-2026-0101")
    line = q["lines"][0]
    was = line["unit_price"]
    q["write_date"], line["unit_price"] = T1, 0.5
    [c] = sync(conn, erp)["changes"]
    assert c["kind"] == "quote" and c["record"].startswith("Quote Q-2026-0101, ") and c["fields"] == []
    assert c["where"] == {"lane": "data", "quote": "Q-2026-0101"}
    [ln] = c["lines"]
    assert ln["outcome"] == "applied" and ln["record"].startswith(line["part_ref"] + ", ")
    assert ln["fields"] == [{"field": "unit_price", "label": "Unit price", "from": round(was, 6), "to": 0.5}]
    assert c["margin"]["to"] < c["margin"]["from"] and c["margin"]["floor"]


def test_a_new_supplier_price_is_traced_to_its_event(conn, erp):
    sync(conn, erp)
    erp.records["supplier_price"].append({"erp_id": 9001, "write_date": T1, "material_ref": "MAT-EPDM-70", "supplier_ref": "V-MWP",
                                          "cost_per_lb": 2.35, "effective_date": "2026-12-01", "is_costing": True})
    s = sync(conn, erp)
    [c] = s["changes"]
    assert c["outcome"] == "new_price" and c["event_id"] == s["events"][0]
    assert c["record"] == "EPDM 70 Shore A compound from Midwest Polymer Supply"
    assert {f["field"]: (f["from"], f["to"]) for f in c["fields"]} == {"cost_per_lb": (2.1, 2.35), "effective_date": (None, "2026-12-01")}


def test_an_edit_to_something_margin_guard_does_not_read_says_so(conn, erp):
    sync(conn, erp)
    erp.find("customer", ref="C-01")["write_date"] = T1         # e.g. a website changed in Odoo
    [c] = sync(conn, erp)["changes"]
    assert c["outcome"] == "no_effect" and c["record"].startswith("Customer C-01") and "Buyer phone" in c["reads"]


def test_a_conflict_is_traced_with_both_values(conn, erp):
    sync(conn, erp)
    conn.execute("UPDATE customers SET buyer_phone = '(312) 555-9999' WHERE id = 'C-01'")
    c = erp.find("customer", ref="C-01")
    c["write_date"], c["buyer_phone"] = T1, "(312) 555-0000"
    [t] = sync(conn, erp)["changes"]
    assert t["outcome"] == "conflict"
    assert t["fields"] == [{"field": "buyer_phone", "label": "Buyer phone", "from": "(312) 555-9999", "to": "(312) 555-0000"}]


def test_a_quote_shows_what_the_erp_changed_on_it(conn, erp, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    sync(conn, erp)
    q = erp.find("quote", ref="Q-2026-0101")
    q["write_date"], q["lines"][0]["unit_price"] = T1, 0.5
    sync(conn, erp)
    monkeypatch.setattr(api, "_conn", conn)
    with TestClient(api.app) as c:
        [ch] = c.get("/api/data/quotes/Q-2026-0101").json()["erp_changes"]
        assert ch["lines"][0]["fields"][0]["to"] == 0.5 and ch["sync_id"]
        assert c.get("/api/data/quotes/Q-2026-0102").json()["erp_changes"] == []
