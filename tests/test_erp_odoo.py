"""The Odoo JSON-2 client and the demo-shop loader, with no Odoo running: a mocked HTTP
transport for the client, and a recording fake for the loader."""

import json
from collections import defaultdict
from itertools import count

import httpx
import pytest

from margin_guard.erp import odoo_seed
from margin_guard.erp.odoo import OdooClient, OdooError
from margin_guard.money import D

# ------------------------------------------------------------------ client


def _client(handler) -> OdooClient:
    return OdooClient(url="http://odoo.test", db="shop", key="k123", transport=httpx.MockTransport(handler))


def test_calls_json2_with_bearer_key_and_database():
    seen = {}

    def handler(req: httpx.Request):
        seen.update(url=str(req.url), auth=req.headers["authorization"], db=req.headers["x-odoo-database"],
                    body=json.loads(req.content))
        return httpx.Response(200, json=[{"id": 7, "name": "Midwest Polymer Supply"}])

    rows = _client(handler).search_read("res.partner", [["ref", "=", "V-MWP"]], ["name"], limit=1)
    assert rows[0]["id"] == 7
    assert seen == {"url": "http://odoo.test/json/2/res.partner/search_read", "auth": "bearer k123", "db": "shop",
                    "body": {"domain": [["ref", "=", "V-MWP"]], "fields": ["name"], "limit": 1}}


def test_reads_retry_a_dropped_connection(monkeypatch):
    monkeypatch.setattr("margin_guard.erp.odoo.time.sleep", lambda s: None)
    tries = count(1)

    def handler(req):
        if next(tries) == 1:
            raise httpx.ConnectError("reset")
        return httpx.Response(200, json=3)

    assert _client(handler).call("sale.order", "search_count", domain=[]) == 3


def test_writes_never_retry(monkeypatch):
    monkeypatch.setattr("margin_guard.erp.odoo.time.sleep", lambda s: None)
    tries = []

    def handler(req):
        tries.append(1)
        raise httpx.ConnectError("reset")

    with pytest.raises(OdooError, match="unreachable"):
        _client(handler).create("res.partner", [{"name": "x"}])
    assert len(tries) == 1            # a create that reached Odoo must not be made twice


def test_odoo_errors_carry_odoos_message():
    def handler(req):
        return httpx.Response(422, json={"name": "odoo.exceptions.ValidationError", "message": "Missing required fields"})

    with pytest.raises(OdooError, match="Missing required fields"):
        _client(handler).create("product.product", [{}])


def test_no_key_is_a_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv("MG_ODOO_KEY", raising=False)
    monkeypatch.setattr("margin_guard.erp.odoo.KEY_FILE", tmp_path / "missing")
    with pytest.raises(OdooError, match="setup"):
        OdooClient()


# ------------------------------------------------------------------ loader


class FakeOdoo:
    """Records every call; hands out ids like Odoo would."""

    def __init__(self):
        self.ids = count(100)
        self.created = defaultdict(list)
        self.calls = []

    def call(self, model, method, **kw):
        self.calls.append((model, method, kw))
        return 0 if method == "search_count" else True

    def create(self, model, vals_list, context=None):
        ids = [next(self.ids) for _ in vals_list]
        self.created[model] += [dict(v, id=i) for v, i in zip(vals_list, ids)]
        return ids

    def write(self, model, ids, vals):
        self.calls.append((model, "write", {"ids": ids, "vals": vals}))
        return True

    def search_read(self, model, domain, fields, **kw):
        if model == "product.product":
            return [{"id": i, "product_tmpl_id": [i + 10_000, "t"]} for i in domain[0][2]]
        return [{"id": 1}]

    def xmlid(self, module, name):
        return {"product_uom_lb": 19, "product_uom_unit": 1}[name]


@pytest.fixture(scope="module")
def loaded():
    fake = FakeOdoo()
    counts = odoo_seed.load(fake, say=lambda s: None)
    return fake, counts


def test_loads_the_whole_shop(loaded):
    fake, counts = loaded
    assert counts["suppliers"] == 7 and counts["customers"] == 24 and counts["materials"] == 12 and counts["parts"] == 40
    assert counts["quotes_open"] == 150 and counts["orders_won"] == 88 and counts["quotes_lost"] == 32
    assert counts["vendor_bills"] > 0
    assert {p["ref"] for p in fake.created["res.partner"] if p.get("supplier_rank")} >= {"V-MWP", "V-RCB"}


def test_supplier_prices_are_dated_and_end_before_the_next(loaded):
    fake, _ = loaded
    by_key = defaultdict(list)
    for s in fake.created["product.supplierinfo"]:
        by_key[(s["partner_id"], s["product_tmpl_id"])].append(s)
    for rows in by_key.values():
        rows.sort(key=lambda s: s["date_start"])
        for a, b in zip(rows, rows[1:]):
            assert a["date_end"] < b["date_start"]
        assert rows[-1]["date_end"] is False                      # the current price is open-ended
    assert {s["sequence"] for s in fake.created["product.supplierinfo"]} <= {1, 10}
    assert all(s["product_uom_id"] == 19 for s in fake.created["product.supplierinfo"])   # $/lb


def test_bom_lines_are_gross_pounds_with_scrap(loaded):
    fake, _ = loaded
    door_seal = next(b for b in fake.created["mrp.bom"] if b["code"] == "P-1001")
    line = door_seal["bom_line_ids"][0][2]
    assert line["product_qty"] == pytest.approx(0.42 * 1.06, abs=1e-4) and line["product_uom_id"] == 19


def test_won_orders_keep_their_order_date(loaded):
    fake, _ = loaded
    confirms = [c for c in fake.calls if c[1] == "action_confirm"]
    redates = [c for c in fake.calls if c[0] == "sale.order" and c[1] == "write"]
    assert len(confirms) == 88 and len(redates) == 88
    assert all(r[2]["vals"]["date_order"].endswith("08:00:00") for r in redates)
    cancels = [c for c in fake.calls if c[1] == "action_cancel"]
    assert cancels and cancels[0][2]["context"] == {"disable_cancel_warning": True}


def test_quote_lines_carry_price_and_cost_when_quoted(loaded):
    fake, _ = loaded
    q = next(o for o in fake.created["sale.order"] if o["name"] == "Q-2026-0101")
    line = q["order_line"][0][2]
    assert line["price_unit"] > line["purchase_price"] > 0


def test_vendor_bill_lines_are_in_pounds(loaded):
    fake, _ = loaded
    lines = [ln[2] for b in fake.created["account.move"] for ln in b["invoice_line_ids"]]
    materials = [ln for ln in lines if ln.get("product_id")]
    charges = [ln for ln in lines if not ln.get("product_id")]
    assert all(ln["product_uom_id"] == 19 for ln in materials)
    # Every material price is per pound, bag and hundredweight prices included.
    assert all(D(str(ln["price_unit"])) < D(50) for ln in materials)
    silicone = next(ln for ln in materials if "Silicone" in ln["name"])      # 20 bags of 25 kg at $300
    assert silicone["quantity"] == pytest.approx(20 * 25 / 0.45359237, abs=0.001)
    # Freight matches no material: it goes in as billed, with no product and no unit.
    freight = next(ln for ln in charges if ln["name"].startswith("Freight"))
    assert (freight["quantity"], freight["price_unit"]) == (1, 85.0) and "product_uom_id" not in freight


def test_does_nothing_when_already_loaded():
    fake = FakeOdoo()
    fake.call = lambda model, method, **kw: 1 if method == "search_count" else True
    assert odoo_seed.load(fake, say=lambda s: None) == {}
    assert not fake.created
