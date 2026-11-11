"""Invoice price drift: lines billed above the price on file become cards; the rest is accounted for."""

import json
from pathlib import Path

import pytest
from test_coordinator import POLICY_DECIDER

from margin_guard import actions, coordinator, invoices
from margin_guard.config import ROOT
from margin_guard.importer import ImportFailed

DEMO = ROOT / "data" / "invoices_demo.csv"
HEADER = "invoice_no,line_no,invoice_date,vendor_id,item,qty,unit,unit_price,pack_qty\n"


def _csv(tmp_path: Path, *lines: str) -> Path:
    p = tmp_path / "inv.csv"
    p.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return p


def test_demo_export(conn):
    r = invoices.check(conn, DEMO)
    assert (r["lines"], r["at_price"], r["above"], r["below"], len(r["not_judged"])) == (12, 6, 3, 1, 2)
    assert r["overpaid_usd"] == pytest.approx(728.21)
    drifts = {d["material_id"]: d for d in r["drifts"]}
    assert set(drifts) == {"MAT-CB-N550", "MAT-VMQ-50"}
    assert drifts["MAT-CB-N550"]["invoices"] == 2 and drifts["MAT-CB-N550"]["overpaid_usd"] == pytest.approx(350.00)
    assert drifts["MAT-CB-N550"]["effective_date"] == "2026-10-02"          # the first invoice at the new price


def test_overpaid_uses_the_lbs_actually_billed(conn, tmp_path):
    # 20 bags of 25 kg at $300 a bag vs $5.10/lb on file: 20 * 300 - 20 * 25 * 2.20462... * 5.10
    r = invoices.check(conn, _csv(tmp_path, "S-1,1,2026-10-05,V-SUM,silicone 50,20,kg,300,25"))
    assert r["overpaid_usd"] == pytest.approx(6000 - 20 * 25 / 0.45359237 * 5.10, abs=0.01)


def test_within_half_a_percent_is_at_price(conn, tmp_path):
    r = invoices.check(conn, _csv(tmp_path, "F-1,1,2026-10-08,V-FLT,FKM 75,100,lb,14.87,"))   # +0.47%
    assert r["at_price"] == 1 and not r["drifts"]


def test_rerun_checks_nothing_twice(conn):
    invoices.check(conn, DEMO)
    again = invoices.check(conn, DEMO)
    assert again["already_on_file"] == 12 and not again["drifts"]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE source_ref LIKE 'invoices:%'").fetchone()[0] == 2


def test_alternate_supplier_is_checked_against_its_own_price(conn, tmp_path):
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-EPDM-70', 'V-KRD', 2.30, '2026-09-01')")
    at = invoices.check(conn, _csv(tmp_path, "K-1,1,2026-10-10,V-KRD,EPDM 70,500,lb,2.30,"))
    assert at["at_price"] == 1                                         # not "above Midwest's $2.10"
    above = invoices.check(conn, _csv(tmp_path, "K-2,1,2026-10-11,V-KRD,EPDM 70,500,lb,2.45,"))
    assert above["drifts"][0]["old_cost_per_lb"] == pytest.approx(2.30)


def test_what_cannot_be_judged_is_reported_not_guessed(conn, tmp_path):
    r = invoices.check(conn, _csv(tmp_path,
                                  "K-1,1,2026-10-10,V-KRD,EPDM 70,500,lb,2.45,",        # no Keystone price on file
                                  "R-1,1,2026-10-10,V-RCB,Freight surcharge,1,lb,85,",  # not an item we stock
                                  "K-2,1,2026-10-10,V-KRD,Black 70,500,lb,2.28,"))      # ambiguous
    assert not r["drifts"] and len(r["not_judged"]) == 3
    assert any("no V-KRD price on file" in n for n in r["not_judged"])
    assert any("can't tell which" in n for n in r["not_judged"])


def test_a_bad_file_loads_nothing(conn, tmp_path):
    bad = _csv(tmp_path,
               "A-1,1,2026-10-01,V-MWP,EPDM 70,10,gallon,2.10,",
               "A-1,1,2026-10-01,V-MWP,EPDM 70,10,lb,2.10,",
               "A-2,1,2026-10-01,V-NOPE,EPDM 70,10,lb,2.10,",
               "A-3,1,10/01/2026,V-MWP,EPDM 70,10,lb,2.10,")
    with pytest.raises(ImportFailed) as exc:
        invoices.check(conn, bad)
    text = " ".join(exc.value.problems)
    assert "gallon" in text and "duplicate invoice line A-1/1" in text and "invoice_date" in text and "V-NOPE" in text
    assert conn.execute("SELECT COUNT(*) FROM invoice_lines").fetchone()[0] == 0


def test_drift_card_applies_as_a_price_change(conn):
    invoices.check(conn, DEMO)
    coordinator.run(conn, POLICY_DECIDER)
    cards = {json.loads(r["facts"])["material_id"]: r for r in conn.execute(
        "SELECT * FROM proposals WHERE kind = 'event_review'")}
    card = cards["MAT-CB-N550"]
    assert card["rationale"].startswith("Invoice needs a person")
    event_id = actions.resolve_review(conn, card["id"], "MAT-CB-N550")
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE id = ?", (event_id,)).fetchone()[0])
    assert payload["vendor_id"] == "V-RCB" and payload["new_cost_per_lb"] == pytest.approx(1.14)
    assert payload["effective_date"] == "2026-10-02"
    result = coordinator.run(conn, POLICY_DECIDER)[event_id]
    assert result["affected_quotes"] > 0


def test_drift_card_can_be_dismissed(conn):
    invoices.check(conn, DEMO)
    coordinator.run(conn, POLICY_DECIDER)
    pid = conn.execute("SELECT id FROM proposals WHERE kind = 'event_review'").fetchone()[0]
    assert actions.dismiss_review(conn, pid, "freight error, disputed")["status"] == "rejected"
