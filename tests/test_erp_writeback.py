"""Writing approved decisions back to the ERP: the outbox (queued with the approval) and the
Odoo writer (checked against Odoo before every write), against a stateful fake Odoo."""

import json
from itertools import count

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import PERFECT_EXTRACTIONS

from margin_guard import actions, coordinator, events, ingest
from margin_guard.erp import outbox
from margin_guard.erp.odoo import OdooError
from margin_guard.erp.odoo_writer import push
from margin_guard.parser import EventDraft


class FakeOdoo:
    """Just enough of Odoo's ORM for the writer: records by model, a domain matcher, and a log."""

    def __init__(self):
        self.ids = count(1000)
        self.db = {m: {} for m in ("sale.order", "sale.order.line", "mail.activity", "mail.message", "product.supplierinfo",
                                   "product.product", "res.partner", "ir.model")}
        self.db["ir.model"][1] = {"id": 1, "model": "sale.order"}
        self.writes = []
        self.down = False

    def add(self, model, **vals):
        i = vals.pop("id", None) or next(self.ids)
        self.db[model][i] = {"id": i, **vals}
        return i

    def _match(self, r, d):
        f, op, v = d
        val = r.get(f)
        if isinstance(val, list):
            val = val[0]
        return val in v if op == "in" else (val == v or (v is False and not val))

    def search_read(self, model, domain, fields, **kw):
        rows = [r for r in self.db[model].values() if all(self._match(r, d) for d in domain)]
        return [dict(r) for r in rows]

    def create(self, model, vals_list, context=None):
        if self.down:
            raise OdooError("Odoo at http://odoo.test is unreachable")
        if model == "mail.activity":         # Odoo fills in res_model from res_model_id
            vals_list = [dict(v, res_model=self.db["ir.model"][v["res_model_id"]]["model"]) for v in vals_list]
        return [self.add(model, **v) for v in vals_list]

    def write(self, model, ids, vals):
        if self.down:
            raise OdooError("Odoo at http://odoo.test is unreachable")
        self.writes.append((model, ids, vals))
        for i in ids:
            self.db[model][i].update(vals)
        return True

    def call(self, model, method, **kw):
        if method == "message_post":
            assert kw.get("body_is_html") is True                 # Odoo would escape it otherwise
            self.add("mail.message", res_id=kw["ids"][0], body=kw["body"])
            return 1
        raise AssertionError(f"unexpected {model}.{method}")

    def xmlid(self, module, name):
        return {"mail_activity_data_call": 2, "product_uom_lb": 19}[name]


@pytest.fixture
def shop(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, POLICY_DECIDER)
    return conn


@pytest.fixture
def odoo(shop):
    """An Odoo holding the shop's quotes, suppliers and materials, linked the way a sync links them."""
    o = FakeOdoo()
    link = lambda kind, erp, local, snap: shop.execute(  # noqa: E731
        "INSERT INTO erp_links (system, kind, erp_id, local_id, snapshot) VALUES ('odoo', ?, ?, ?, ?)", (kind, erp, local, json.dumps(snap)))
    users = {}
    for q in shop.execute("SELECT q.id, c.account_manager FROM quotes q JOIN customers c ON c.id = q.customer_id"):
        uid = users.setdefault(q["account_manager"], len(users) + 1)
        lines = []
        for ln in shop.execute("SELECT * FROM quote_lines WHERE quote_id = ? ORDER BY id", (q["id"],)):
            lid = o.add("sale.order.line", price_unit=ln["unit_price"], product_uom_qty=ln["qty"], product_id=[1, ln["part_id"]])
            lines.append(lid)
            link("quote_line", lid, str(ln["id"]), {"part_ref": ln["part_id"], "qty": ln["qty"], "unit_price": ln["unit_price"]})
        oid = o.add("sale.order", name=q["id"], state="draft", user_id=[uid, q["account_manager"]], order_line=lines)
        link("quote", oid, q["id"], {})
    for v in shop.execute("SELECT id FROM vendors"):
        link("supplier", o.add("res.partner", ref=v["id"]), v["id"], {})
    for m in shop.execute("SELECT id FROM materials"):
        pid = o.add("product.product", default_code=m["id"])
        o.db["product.product"][pid]["product_tmpl_id"] = [pid + 50_000, m["id"]]
        link("material", pid, m["id"], {})
    shop.commit()
    return o


def _pending(conn, action, quote=None):
    sql = "SELECT * FROM proposals WHERE status = 'pending' AND kind = 'quote_action' AND action = ?"
    args = [action]
    if quote:
        sql, args = sql + " AND quote_id = ?", args + [quote]
    return conn.execute(sql + " ORDER BY exposure_usd DESC, id LIMIT 1", args).fetchone()


def _queued(conn, kind):
    return [json.loads(r["payload"]) | {"_id": r["id"], "_status": r["status"]}
            for r in conn.execute("SELECT * FROM erp_outbox WHERE kind = ? ORDER BY id", (kind,))]


def _line_prices(o, quote):
    order = next(r for r in o.db["sale.order"].values() if r["name"] == quote)
    return [o.db["sale.order.line"][i]["price_unit"] for i in order["order_line"]]


# ------------------------------------------------------------------ queueing


def test_a_shop_never_linked_to_an_erp_queues_nothing(shop):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    assert shop.execute("SELECT COUNT(*) FROM erp_outbox").fetchone()[0] == 0


def test_an_approved_reprice_is_queued_with_the_prices_it_replaces(shop, odoo):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    [q] = _queued(shop, "quote_prices")
    revs = shop.execute("SELECT old_price, new_price FROM quote_revisions WHERE proposal_id = ?", (p["id"],)).fetchall()
    assert [(ln["old"], ln["new"]) for ln in q["lines"]] == [(r["old_price"], r["new_price"]) for r in revs]
    assert "MAT-" not in q["note"]                                     # the material's name, not its id
    assert _queued(shop, "supplier_price")                             # acting on the decision puts the price in the ERP


def test_a_price_that_came_from_the_erp_is_never_written_back(shop, odoo):
    ev = events.append(shop, EventDraft("price_change.detected", "k-odoo", {
        "material_id": "MAT-EPDM-70", "vendor_id": "V-MWP", "new_cost_per_lb": 2.5, "effective_date": "2026-12-01",
        "source": "odoo"}), source_ref="odoo:product.supplierinfo:9")
    outbox.supplier_price(shop, ev)
    assert not _queued(shop, "supplier_price")


# ------------------------------------------------------------------ writing quote prices


def test_push_writes_the_prices_once_with_a_note(shop, odoo):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    r = push(shop, odoo)
    assert any("quote_prices" in s for s in r["sent"]) and not r["conflict"]
    new = [x["new_price"] for x in shop.execute("SELECT new_price FROM quote_revisions WHERE proposal_id = ?", (p["id"],))]
    changed = [x for x in _line_prices(odoo, p["quote_id"]) if x in new]
    assert sorted(changed) == sorted(new)
    assert any("Revised prices approved" in m["body"] for m in odoo.db["mail.message"].values())
    assert not any(push(shop, odoo).values())                          # nothing left to send


def test_a_line_changed_in_odoo_first_stops_the_write_and_asks(shop, odoo):
    p = _pending(shop, "reprice")
    order = next(r for r in odoo.db["sale.order"].values() if r["name"] == p["quote_id"])
    odoo.db["sale.order.line"][order["order_line"][0]]["price_unit"] += 0.25           # a colleague edits it in Odoo
    actions.review(shop, p["id"], "approve")
    before = list(odoo.writes)
    r = push(shop, odoo)
    assert r["conflict"] and "someone changed it there" in r["conflict"][0]
    assert not [w for w in odoo.writes[len(before):] if w[0] == "sale.order.line"]      # nothing half-written
    q = shop.execute("SELECT * FROM proposals WHERE rule_id = 'erp_conflict'").fetchone()
    assert q["status"] == "pending" and json.loads(q["facts"])["kind"] == "erp_conflict"

    item = _queued(shop, "quote_prices")[0]["_id"]
    assert push(shop, odoo, force_id=item)["sent"]                     # a person looked and wrote it anyway
    assert shop.execute("SELECT status FROM proposals WHERE id = ?", (q["id"],)).fetchone()[0] == "approved"


def test_a_confirmed_order_is_not_repriced(shop, odoo):
    p = _pending(shop, "reprice")
    next(r for r in odoo.db["sale.order"].values() if r["name"] == p["quote_id"])["state"] = "sale"
    actions.review(shop, p["id"], "approve")
    assert "no longer a quotation" in push(shop, odoo)["conflict"][0]


def test_a_write_that_already_landed_is_not_made_twice(shop, odoo):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    for ln in _queued(shop, "quote_prices")[0]["lines"]:              # the write landed; its response was lost
        lid = shop.execute("SELECT erp_id FROM erp_links WHERE kind = 'quote_line' AND local_id = ?", (str(ln["line_id"]),)).fetchone()[0]
        odoo.db["sale.order.line"][lid]["price_unit"] = ln["new"]
    r = push(shop, odoo)
    assert any("already in Odoo" in s for s in r["sent"])
    assert not odoo.db["mail.message"]                                 # no second note either


def test_odoo_down_leaves_the_write_queued(shop, odoo):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    odoo.down = True
    r = push(shop, odoo)
    assert r["failed"] and not r["sent"]
    odoo.down = False
    assert push(shop, odoo)["sent"]                                    # the next push sends it


# ------------------------------------------------------------------ calls and supplier prices


def test_an_approved_call_becomes_one_activity_for_the_account_manager(shop, odoo):
    p = _pending(shop, "contact_customer")
    actions.review(shop, p["id"], "approve")
    push(shop, odoo)
    [a] = odoo.db["mail.activity"].values()
    order = next(r for r in odoo.db["sale.order"].values() if r["name"] == p["quote_id"])
    assert a["res_id"] == order["id"] and a["activity_type_id"] == 2 and a["user_id"] == order["user_id"][0]
    shop.execute("UPDATE erp_outbox SET status = 'pending' WHERE kind = 'call_task'")      # a retry
    push(shop, odoo)
    assert len(odoo.db["mail.activity"]) == 1


def test_a_supplier_price_closes_the_line_before_it(shop, odoo):
    tmpl = next(r["product_tmpl_id"][0] for r in odoo.db["product.product"].values() if r["default_code"] == "MAT-EPDM-70")
    partner = next(r["id"] for r in odoo.db["res.partner"].values() if r["ref"] == "V-MWP")
    old = odoo.add("product.supplierinfo", partner_id=[partner, "x"], product_tmpl_id=[tmpl, "x"], price=2.10, min_qty=0,
                   date_start="2026-07-01", date_end=False, sequence=1)
    shop.execute("INSERT INTO erp_outbox (system, kind, idempotency_key, payload) VALUES ('odoo', 'supplier_price', 'k1', ?)",
                 (json.dumps({"material_id": "MAT-EPDM-70", "vendor_id": "V-MWP", "cost_per_lb": 2.27, "effective_date": "2026-11-01"}),))
    shop.commit()
    push(shop, odoo)
    assert odoo.db["product.supplierinfo"][old]["date_end"] == "2026-10-31"
    new = next(r for r in odoo.db["product.supplierinfo"].values() if r["id"] != old)
    assert (new["price"], new["date_start"], new["date_end"], new["sequence"]) == (2.27, "2026-11-01", False, 1)


def test_a_different_price_already_in_odoo_for_that_date_is_a_conflict(shop, odoo):
    tmpl = next(r["product_tmpl_id"][0] for r in odoo.db["product.product"].values() if r["default_code"] == "MAT-EPDM-70")
    partner = next(r["id"] for r in odoo.db["res.partner"].values() if r["ref"] == "V-MWP")
    odoo.add("product.supplierinfo", partner_id=[partner, "x"], product_tmpl_id=[tmpl, "x"], price=2.30, min_qty=0,
             date_start="2026-11-01", date_end=False, sequence=1)
    shop.execute("INSERT INTO erp_outbox (system, kind, idempotency_key, payload) VALUES ('odoo', 'supplier_price', 'k2', ?)",
                 (json.dumps({"material_id": "MAT-EPDM-70", "vendor_id": "V-MWP", "cost_per_lb": 2.27, "effective_date": "2026-11-01"}),))
    shop.commit()
    assert "already has V-MWP's price" in push(shop, odoo)["conflict"][0]


# ------------------------------------------------------------------ undo


def test_undo_cancels_a_queued_write_and_reverses_a_sent_one(shop, odoo):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    actions.reopen(shop, p["id"])                                      # undone before it was sent
    assert [x["_status"] for x in _queued(shop, "quote_prices")] == ["cancelled"]

    actions.review(shop, p["id"], "approve")                           # approved again: a new write, not a lost one
    assert [x["_status"] for x in _queued(shop, "quote_prices")] == ["cancelled", "pending"]
    push(shop, odoo)
    old = [x["old_price"] for x in shop.execute("SELECT old_price FROM quote_revisions WHERE proposal_id = ?", (p["id"],))]

    actions.reopen(shop, p["id"])                                      # undone after it was sent
    [undo] = [x for x in _queued(shop, "quote_prices") if x.get("undoes")]
    assert undo["_status"] == "pending"
    push(shop, odoo)
    prices = _line_prices(odoo, p["quote_id"])
    assert all(x in prices for x in old)                               # Odoo has the quoted prices again


# ------------------------------------------------------------------ the console's ERP page (api.py)


class _Now:
    """threading.Thread that runs its target at start(), so a job finishes before the request returns."""

    def __init__(self, target, daemon=None):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def client(shop, odoo, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    from margin_guard.erp import odoo as odoo_mod
    published = []
    monkeypatch.setattr(api, "_conn", shop)
    monkeypatch.setattr(api, "DB_PATH", shop.execute("PRAGMA database_list").fetchone()["file"])
    monkeypatch.setattr(api.threading, "Thread", _Now)
    monkeypatch.setattr(api.bus, "publish", lambda kind, data: published.append((kind, data)))
    monkeypatch.setattr(odoo_mod, "settings", lambda: ("http://odoo.test", "margin_guard", "key"))
    monkeypatch.setattr(odoo_mod, "OdooClient", lambda **kw: odoo)
    odoo.call = (lambda real: lambda model, method, **kw: 3 if method == "search_count" else real(model, method, **kw))(odoo.call)
    with TestClient(api.app) as c:
        c.published = published
        yield c


def test_the_erp_page_shows_what_is_linked_and_what_is_waiting(client, shop):
    p = _pending(shop, "reprice")
    actions.review(shop, p["id"], "approve")
    s = client.get("/api/erp").json()
    assert s["configured"] and s["reachable"] and s["problem"] is None
    linked = {x["kind"]: x["count"] for x in s["linked"]}
    assert linked["quote"] == shop.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
    assert s["write_counts"] == {"pending": 2}                           # the new prices, and the supplier price behind them
    assert {w["kind"]: w["label"] for w in s["writes"]}["quote_prices"] == f"Revised prices on {p['quote_id']}"


def test_the_erp_page_says_when_odoo_is_not_set_up(client, monkeypatch):
    from margin_guard.erp import odoo as odoo_mod
    monkeypatch.setattr(odoo_mod, "settings", lambda: ("http://odoo.test", "margin_guard", None))
    s = client.get("/api/erp").json()
    assert not s["configured"] and not s["reachable"] and s["problem"] == "not set up"


def test_a_refused_write_can_be_written_anyway_from_the_console(client, shop, odoo):
    p = _pending(shop, "reprice")
    order = next(r for r in odoo.db["sale.order"].values() if r["name"] == p["quote_id"])
    odoo.db["sale.order.line"][order["order_line"][0]]["price_unit"] += 0.25           # a colleague edits it in Odoo
    actions.review(shop, p["id"], "approve")
    item = _queued(shop, "quote_prices")[0]["_id"]
    assert client.post(f"/api/erp/outbox/{item}/force").status_code == 400            # not refused yet: nothing to force

    assert client.post("/api/erp/push").json() == {"started": True}
    assert ("erp.pushed", {"sent": 1, "conflict": 1, "failed": 0}) in client.published   # the supplier price went through
    assert {w["id"]: w["status"] for w in client.get("/api/erp").json()["writes"]}[item] == "conflict"

    assert client.post(f"/api/erp/outbox/{item}/force").status_code == 200
    assert ("erp.pushed", {"sent": 1, "conflict": 0, "failed": 0}) in client.published
    assert _line_prices(odoo, p["quote_id"]) == [ln["new"] for ln in _queued(shop, "quote_prices")[0]["lines"]]
    q = shop.execute("SELECT status FROM proposals WHERE rule_id = 'erp_conflict'").fetchone()
    assert q["status"] == "approved"
