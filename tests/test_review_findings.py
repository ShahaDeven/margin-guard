"""Regression tests for the Nov 2026 code-review findings, each reproducing the reported case."""

import json
import sqlite3

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import _ch, _ex

from margin_guard import actions, attachments, catalog, coordinator, events, impact, invoices, quotecheck
from margin_guard.importer import ImportFailed
from margin_guard.parser import normalize

HEADER = "invoice_no,line_no,invoice_date,vendor_id,item,qty,unit,unit_price,pack_qty\n"


def _invoices(conn, tmp_path, *lines):
    f = tmp_path / "inv.csv"
    f.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return invoices.check(conn, f)


def _deliver(conn, sender, extraction, email_id="T"):
    for d in normalize(conn, {"id": email_id, "from_addr": sender}, extraction).drafts:
        events.append(conn, d, "test")
    return coordinator.run(conn, POLICY_DECIDER)


# ------------------------------------------------ P0: exactly one costing supplier, fail closed


def test_no_costing_supplier_fails_closed(conn):
    conn.execute("UPDATE material_vendors SET is_primary = 0 WHERE material_id = 'MAT-EPDM-70'")
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-EPDM-70', 'V-KRD', 2.60, '2026-09-01')")
    # Neither supplier's price is used: before, a missing costing supplier let any supplier's row match.
    assert impact.cost_on(conn, "MAT-EPDM-70", "2026-10-01") != pytest.approx(2.60)
    assert not impact.moves_costing(conn, {"material_id": "MAT-EPDM-70", "vendor_id": "V-MWP"})
    assert not impact.moves_costing(conn, {"material_id": "MAT-EPDM-70", "vendor_id": "V-KRD"})
    assert impact.moves_costing(conn, {"material_id": "MAT-EPDM-70", "vendor_id": None})   # shop entry still counts
    assert catalog.costing_problems(conn) == ["MAT-EPDM-70 has no costing supplier; mark exactly one"]


def test_database_refuses_a_second_costing_supplier(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE material_vendors SET is_primary = 1 WHERE material_id = 'MAT-EPDM-70' AND vendor_id = 'V-KRD'")


def test_import_rejects_a_material_with_no_costing_supplier(conn, tmp_path):
    from test_importer import _edit

    from margin_guard import importer
    importer.export(conn, tmp_path / "csv")
    _edit(tmp_path / "csv", "material_vendors.csv",
          lambda rows: [r.update(is_costing="0") for r in rows if r["material_id"] == "MAT-FKM-75"])
    problems = importer.validate(tmp_path / "csv")[1]
    assert any("MAT-FKM-75 has no costing supplier" in p for p in problems)


def test_overview_reports_costing_problems(conn, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    conn.execute("UPDATE material_vendors SET is_primary = 0 WHERE material_id = 'MAT-FKM-75'")
    monkeypatch.setattr(api, "_conn", conn)
    with TestClient(api.app) as c:
        assert c.get("/api/overview").json()["data_problems"] == ["MAT-FKM-75 has no costing supplier; mark exactly one"]


# ------------------------------------------------ P1: quote check uses the worst margin in the window


def test_quote_check_catches_a_temporary_dip(conn):
    # Up on Nov 1, partly back down on Dec 1: the worst point is in the middle, not at expiry.
    conn.executemany("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date) VALUES (?, ?, ?, ?)",
                     [("MAT-FKM-75", "V-FLT", 18.00, "2026-11-01"), ("MAT-FKM-75", "V-FLT", 15.00, "2026-12-01")])
    cid = conn.execute("SELECT id FROM customers WHERE price_lock_until IS NULL ORDER BY id LIMIT 1").fetchone()[0]
    part = conn.execute("SELECT part_id FROM part_materials WHERE material_id = 'MAT-FKM-75' LIMIT 1").fetchone()[0]
    cost = next(p for p in quotecheck.parts_catalog(conn) if p["id"] == part)["unit_cost_now"]
    r = quotecheck.check(conn, customer_id=cid, valid_days=60, margin_floor=0.25,
                         lines=[{"part_id": part, "qty": 100, "unit_price": round(cost / 0.7, 4)}])
    assert r["worst_date"] == "2026-11-01"
    assert r["worst_margin_during_validity"] < r["margin_at_expiry"] < r["margin_at_issue"]
    assert r["maximum_exposure_usd"] > 0
    # The held price covers the peak cost, so the margin holds even at the worst point.
    held = r["lines"][0]["price_to_hold_margin"]
    again = quotecheck.check(conn, customer_id=cid, valid_days=60, margin_floor=0.25,
                             lines=[{"part_id": part, "qty": 100, "unit_price": held}])
    assert again["worst_margin_during_validity"] == pytest.approx(r["margin_at_issue"], abs=2e-4)


# ------------------------------------------------ P1: incomplete attachments always reach a person


def test_unreadable_attachment_is_reviewed_even_when_the_body_has_a_change(conn):
    email = {"id": "T4", "from_addr": "sales@glelastomers.com",
             "incomplete_attachments": [("scan.pdf", attachments.UNREADABLE, "PDF has no text layer")]}
    drafts = normalize(conn, email, _ex("price_change", [_ch("NBR 70", 2.36, "lb", "2026-11-15")])).drafts
    kinds = sorted(d.event_type for d in drafts)
    assert kinds == ["price_change.detected", "price_change.needs_review"]
    review = next(d for d in drafts if d.event_type == "price_change.needs_review")
    assert "scan.pdf could not be read" in review.payload["review_reasons"][0]


def test_truncated_attachment_is_flagged_and_reviewed(conn):
    rows = "\n".join(f"G{i},{i}" for i in range(attachments.MAX_ROWS + 10)).encode()
    assert attachments.render("long.csv", rows).state == attachments.TRUNCATED
    email = {"id": "T5", "from_addr": "sales@glelastomers.com",
             "incomplete_attachments": [("list.xlsx", attachments.TRUNCATED, "price list cut at 400 rows per sheet")]}
    drafts = normalize(conn, email, _ex("price_change", [_ch("NBR 70", 2.36, "lb", "2026-11-15")])).drafts
    review = next(d for d in drafts if d.event_type == "price_change.needs_review")
    assert "only partly read" in review.payload["review_reasons"][0]


def test_attachment_states():
    assert attachments.render("broken.xlsx", b"not a zip").state == attachments.FAILED
    assert attachments.render("photo.jpg", b"\xff\xd8").state == attachments.UNREADABLE
    assert attachments.render("empty.csv", b"").state == attachments.UNREADABLE
    assert attachments.render("ok.csv", b"Grade,Price\nNBR 70,5.2\n").state == attachments.COMPLETE


# ------------------------------------------------ P1: invoice drift evidence and merging


def test_drift_evidence_comes_from_the_billing_supplier(conn, tmp_path):
    conn.execute("INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date)"
                 " VALUES ('MAT-EPDM-70', 'V-KRD', 2.30, '2026-09-01')")
    _invoices(conn, tmp_path, "K-1,1,2026-10-10,V-KRD,EPDM 70,500,lb,2.45,")
    payload = json.loads(conn.execute("SELECT payload FROM events WHERE idempotency_key LIKE 'drift:V-KRD%'").fetchone()[0])
    assert payload["old_cost_per_lb"] == pytest.approx(2.30)
    assert payload["expected_row"]["vendor_id"] == "V-KRD" and payload["expected_row"]["cost_per_lb"] == pytest.approx(2.30)


def test_later_invoices_join_the_open_card(conn, tmp_path):
    _invoices(conn, tmp_path, "D-1,1,2026-10-02,V-RCB,N550,40,cwt,114,")
    coordinator.run(conn, POLICY_DECIDER)
    r = _invoices(conn, tmp_path, "D-2,1,2026-10-20,V-RCB,N550,30,cwt,114,")
    assert r["drifts"][0]["status"] == "merged"
    facts = json.loads(conn.execute("SELECT facts FROM proposals WHERE kind = 'event_review'").fetchone()[0])
    assert [i["invoice_no"] for i in facts["invoices"]] == ["D-1", "D-2"]
    assert facts["overpaid_usd"] == pytest.approx(350.00)


def test_after_a_decision_later_invoices_raise_a_new_card(conn, tmp_path):
    _invoices(conn, tmp_path, "D-1,1,2026-10-02,V-RCB,N550,40,cwt,114,")
    coordinator.run(conn, POLICY_DECIDER)
    pid = conn.execute("SELECT id FROM proposals WHERE kind = 'event_review'").fetchone()[0]
    actions.dismiss_review(conn, pid, "disputed")
    r = _invoices(conn, tmp_path, "D-3,1,2026-10-25,V-RCB,N550,10,cwt,114,")
    assert r["drifts"][0]["status"] == "new_after_decision"
    assert conn.execute("SELECT status FROM proposals WHERE id = ?", (pid,)).fetchone()[0] == "rejected"
    coordinator.run(conn, POLICY_DECIDER)
    assert conn.execute("SELECT COUNT(*) FROM proposals WHERE kind = 'event_review' AND status = 'pending'").fetchone()[0] == 1


@pytest.mark.parametrize("line_no", ["0.5", "2.9", "0"])
def test_fractional_or_zero_invoice_line_numbers_are_rejected(conn, tmp_path, line_no):
    with pytest.raises(ImportFailed) as exc:
        _invoices(conn, tmp_path, f"X-1,{line_no},2026-10-02,V-RCB,N550,1,cwt,114,")
    assert any("line_no" in p and "whole number" in p for p in exc.value.problems), exc.value.problems


# ------------------------------------------------ P1: approved decisions get a correction card


@pytest.fixture
def approved(conn):
    """An approved Nov 15 decision on a quote using NBR 70 and N550, then a Nov 1 N550 change arrives."""
    q = conn.execute("""SELECT DISTINCT q.id FROM quotes q JOIN quote_lines ql ON ql.quote_id = q.id
                        WHERE q.status = 'open' AND ql.part_id = 'P-1007' AND q.valid_until >= '2026-11-15'
                        ORDER BY q.id LIMIT 1""").fetchone()[0]
    _deliver(conn, "sales@glelastomers.com", _ex("price_change", [_ch("NBR 70", 2.36, "lb", "2026-11-15")]), "E-NBR")
    orig = conn.execute("SELECT id FROM proposals WHERE quote_id = ? AND kind = 'quote_action'", (q,)).fetchone()[0]
    actions.review(conn, orig, "approve")
    _deliver(conn, "customerservice@ridgelinecarbon.com", _ex("price_change", [_ch("N550", 1.30, "lb", "2026-11-01")]),
             "E-N550")
    return conn, q, orig


def _correction(conn, orig):
    return conn.execute("""SELECT * FROM proposals WHERE json_extract(facts, '$.kind') = 'correction'
                           AND json_extract(facts, '$.corrects') = ? ORDER BY id DESC""", (orig,)).fetchone()


def test_approved_decision_gets_a_linked_correction(approved):
    conn, q, orig = approved
    assert conn.execute("SELECT status FROM proposals WHERE id = ?", (orig,)).fetchone()[0] == "approved"
    card = _correction(conn, orig)
    assert card is not None and card["status"] == "pending" and card["quote_id"] == q
    facts = json.loads(card["facts"])
    assert facts["original"]["final_action"] and facts["revised"]["exposure_usd"] > facts["original"]["exposure_usd"]


def test_keeping_the_decision_records_it_and_changes_nothing(approved):
    conn, _, orig = approved
    card = _correction(conn, orig)
    actions.dismiss_review(conn, card["id"], "Kept the original decision")
    assert conn.execute("SELECT status FROM proposals WHERE id = ?", (orig,)).fetchone()[0] == "approved"
    assert conn.execute("SELECT reviewer_note FROM proposals WHERE id = ?", (card["id"],)).fetchone()[0] == "Kept the original decision"


def test_redeciding_raises_a_new_linked_card(approved):
    conn, q, orig = approved
    card = _correction(conn, orig)
    event_id = actions.redecide_correction(conn, card["id"])
    coordinator.run(conn, POLICY_DECIDER)
    new = conn.execute("SELECT * FROM proposals WHERE event_id = ?", (event_id,)).fetchone()
    assert new["quote_id"] == q and new["status"] == "pending" and new["kind"] == "quote_action"
    assert json.loads(new["facts"])["corrects"]["proposal_id"] == orig
    assert conn.execute("SELECT status FROM proposals WHERE id = ?", (orig,)).fetchone()[0] == "approved"
    with pytest.raises(actions.ActionError):
        actions.redecide_correction(conn, card["id"])


def test_a_tiny_change_does_not_raise_a_correction(conn):
    q = conn.execute("""SELECT DISTINCT q.id FROM quotes q JOIN quote_lines ql ON ql.quote_id = q.id
                        WHERE q.status = 'open' AND ql.part_id = 'P-1007' AND q.valid_until >= '2026-11-15'
                        ORDER BY q.id LIMIT 1""").fetchone()[0]
    _deliver(conn, "sales@glelastomers.com", _ex("price_change", [_ch("NBR 70", 2.36, "lb", "2026-11-15")]), "E-NBR")
    orig = conn.execute("SELECT id FROM proposals WHERE quote_id = ? AND kind = 'quote_action'", (q,)).fetchone()[0]
    actions.review(conn, orig, "approve")
    _deliver(conn, "customerservice@ridgelinecarbon.com", _ex("price_change", [_ch("N550", 1.0901, "lb", "2026-11-01")]),
             "E-N550")
    assert _correction(conn, orig) is None
