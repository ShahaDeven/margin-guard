"""Reviewer actions and the HTTP layer over them, with no API calls."""

import json

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import PERFECT_EXTRACTIONS

from margin_guard import actions, coordinator, impact, ingest


@pytest.fixture
def processed(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, POLICY_DECIDER)
    return conn


def _first(conn, where):
    row = conn.execute(f"SELECT id FROM proposals WHERE status = 'pending' AND {where} ORDER BY id LIMIT 1").fetchone()
    assert row, f"no pending proposal where {where}"
    return row["id"]


def test_approve_reprice_updates_quote_and_outbox(processed):
    pid = _first(processed, "action = 'reprice'")
    facts = actions.get(processed, pid)["facts"]
    p = actions.review(processed, pid, "approve")
    assert p["status"] == "approved" and p["final_action"] == "reprice"
    for ln in facts["lines"]:
        price = processed.execute("SELECT unit_price FROM quote_lines WHERE id = ?", (ln["line_id"],)).fetchone()[0]
        assert price == pytest.approx(ln["proposed_unit_price"])
    changed = sum(1 for ln in facts["lines"] if ln["proposed_unit_price"] != ln["unit_price"])
    assert processed.execute("SELECT COUNT(*) FROM quote_revisions WHERE proposal_id = ?", (pid,)).fetchone()[0] == changed
    [mail] = processed.execute("SELECT * FROM outbox WHERE proposal_id = ?", (pid,)).fetchall()
    assert mail["kind"] == "customer_email"
    assert facts["buyer"]["email"] in mail["recipient"] and facts["buyer"]["name"] in mail["recipient"]


def test_approve_contact_creates_call_task_and_keeps_prices(processed):
    pid = _first(processed, "action = 'contact_customer'")
    facts = actions.get(processed, pid)["facts"]
    actions.review(processed, pid, "approve")
    [task] = processed.execute("SELECT kind, recipient FROM outbox WHERE proposal_id = ?", (pid,)).fetchall()
    assert task["kind"] == "call_task"
    # The call task says who to call and the number, so nobody has to look it up.
    assert facts["buyer"]["phone"] in task["recipient"] and facts["account_manager"]["name"] in task["recipient"]
    for ln in facts["lines"]:
        price = processed.execute("SELECT unit_price FROM quote_lines WHERE id = ?", (ln["line_id"],)).fetchone()[0]
        assert price == pytest.approx(ln["unit_price"])


def test_edit_records_what_the_person_changed(processed):
    pid = _first(processed, "action = 'contact_customer'")
    p = actions.review(processed, pid, "edit", action="reprice", body="Revised pricing attached.", note="small order")
    assert p["status"] == "edited"
    assert (p["action"], p["final_action"]) == ("contact_customer", "reprice")   # proposal kept, verdict beside it
    assert p["final_body"] == "Revised pricing attached." and p["reviewer_note"] == "small order"


def test_edit_without_changes_counts_as_approval(processed):
    pid = _first(processed, "action = 'reprice'")
    p = actions.get(processed, pid)
    assert actions.review(processed, pid, "edit", action=p["action"], body=p["draft_body"])["status"] == "approved"


def test_reject_changes_nothing(processed):
    pid = _first(processed, "action = 'reprice'")
    before = processed.execute("SELECT SUM(unit_price) FROM quote_lines").fetchone()[0]
    assert actions.review(processed, pid, "reject", note="customer already accepted")["status"] == "rejected"
    assert processed.execute("SELECT SUM(unit_price) FROM quote_lines").fetchone()[0] == before
    assert processed.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_a_card_can_only_be_reviewed_once(processed):
    pid = _first(processed, "action = 'reprice'")
    actions.review(processed, pid, "approve")
    with pytest.raises(actions.ActionError, match="already approved"):
        actions.review(processed, pid, "reject")


def test_undo_reprice_restores_prices_and_withdraws_email(processed):
    pid = _first(processed, "action = 'reprice'")
    before = processed.execute("SELECT id, unit_price FROM quote_lines ORDER BY id").fetchall()
    actions.review(processed, pid, "approve")
    p = actions.reopen(processed, pid)
    assert p["status"] == "pending" and p["final_action"] is None
    assert processed.execute("SELECT id, unit_price FROM quote_lines ORDER BY id").fetchall() == before
    assert processed.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    assert processed.execute("SELECT COUNT(*) FROM quote_revisions").fetchone()[0] == 0
    actions.review(processed, pid, "approve")       # and it can be decided again


def test_undo_rule_confirmation_and_rejection(processed):
    rule_id = _first(processed, "decided_by = 'rule' AND kind = 'quote_action'")
    event_id = actions.get(processed, rule_id)["event_id"]
    actions.confirm_rules(processed, event_id)
    assert actions.reopen(processed, rule_id)["status"] == "pending"
    pid = _first(processed, "action = 'contact_customer'")
    actions.review(processed, pid, "reject", note="wrong")
    assert actions.reopen(processed, pid)["reviewer_note"] is None


def test_undo_guards(processed):
    pid = _first(processed, "action = 'reprice'")
    with pytest.raises(actions.ActionError, match="nothing to undo"):
        actions.reopen(processed, pid)
    review_id = processed.execute(
        "SELECT id FROM proposals WHERE kind = 'event_review' AND facts LIKE '%E07%'").fetchone()["id"]
    actions.resolve_review(processed, review_id, "MAT-EPDM-70")
    with pytest.raises(actions.ActionError, match="can't be reopened"):
        actions.reopen(processed, review_id)


def test_undo_refuses_if_the_quote_was_revised_again(processed):
    pid = _first(processed, "action = 'reprice'")
    actions.review(processed, pid, "approve")
    line = processed.execute("SELECT line_id FROM quote_revisions WHERE proposal_id = ?", (pid,)).fetchone()[0]
    processed.execute("UPDATE quote_lines SET unit_price = unit_price + 1 WHERE id = ?", (line,))
    with pytest.raises(actions.ActionError, match="revised again"):
        actions.reopen(processed, pid)


def test_cards_list_every_cost_change_behind_their_numbers(processed):
    # P-1004 uses EPDM 70 and carbon black, which both rise Nov 1. Any card computed
    # after the carbon-black change was recorded must name both, and its P-1004 line
    # must say it is hit by both.
    cb_event = processed.execute(
        "SELECT id FROM events WHERE event_type = 'price_change.detected' AND payload LIKE '%MAT-CB-N550%'"
        " AND source_ref LIKE 'email:%'").fetchone()["id"]
    found = False
    for p in (actions.get(processed, r["id"]) for r in processed.execute(
            "SELECT id FROM proposals WHERE kind = 'quote_action' AND status = 'pending'")):
        f = p["facts"]
        changed = {c["material_id"] for c in f["cost_changes"]}
        for ln in f["lines"]:
            assert set(ln["changed_materials"]) <= changed
            if (ln["part_id"] == "P-1004" and p["event_id"] >= cb_event and f["can_accept_after_change"]
                    and f["effective_date"] >= "2026-11-01"):
                assert {"MAT-EPDM-70", "MAT-CB-N550"} <= set(ln["changed_materials"])
                found = True
        assert f["cost_changes"][0]["material_id"] == f["material_id"]   # the trigger is listed first
    assert found, "expected a live card for a quote containing P-1004"


def test_every_customer_has_contacts(conn):
    managers = {}
    for c in conn.execute("SELECT * FROM customers"):
        assert c["buyer_name"] and c["buyer_phone"].count("555-01") == 1 and c["buyer_email"].endswith(".example")
        assert c["account_manager"] and c["account_manager_phone"]
        managers.setdefault(c["account_manager"], set()).add(c["tier"])
    # Four books, each a mix of key and standard accounts, not one manager per tier.
    assert len(managers) == 4
    assert all(tiers == {"key", "standard"} for tiers in managers.values())


def test_cost_changes_carry_readable_material_names(processed):
    row = processed.execute("SELECT facts FROM proposals WHERE kind = 'quote_action' LIMIT 1").fetchone()
    for c in json.loads(row["facts"])["cost_changes"]:
        assert c["material_name"] and not c["material_name"].startswith("MAT-")


def test_escalated_card_needs_an_action_before_approval(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])

    def broken(_):
        raise RuntimeError("api down")
    coordinator.run(conn, broken)
    pid = _first(conn, "action = 'escalate'")
    with pytest.raises(actions.ActionError, match="choose an action"):
        actions.review(conn, pid, "approve")
    assert actions.review(conn, pid, "edit", action="absorb")["final_action"] == "absorb"


def test_confirm_rules_only_touches_that_events_rule_cards(processed):
    event_id = processed.execute(
        "SELECT event_id FROM proposals WHERE decided_by = 'rule' AND kind = 'quote_action' AND status = 'pending'"
        " GROUP BY event_id ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    pending_rules = processed.execute(
        "SELECT COUNT(*) FROM proposals WHERE event_id = ? AND decided_by = 'rule' AND status = 'pending'"
        " AND kind = 'quote_action'", (event_id,)).fetchone()[0]
    llm_before = processed.execute("SELECT COUNT(*) FROM proposals WHERE decided_by = 'llm' AND status = 'pending'").fetchone()[0]
    assert actions.confirm_rules(processed, event_id) == pending_rules
    assert processed.execute("SELECT COUNT(*) FROM proposals WHERE decided_by = 'llm' AND status = 'pending'").fetchone()[0] == llm_before


def test_resolving_black_70_creates_the_price_change(processed):
    pid = processed.execute(
        "SELECT id FROM proposals WHERE kind = 'event_review' AND facts LIKE '%E07%'").fetchone()["id"]
    event_id = actions.resolve_review(processed, pid, "MAT-EPDM-70")
    ev = processed.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    payload = json.loads(ev["payload"])
    assert ev["event_type"] == "price_change.detected" and ev["status"] == "pending"
    assert payload["material_id"] == "MAT-EPDM-70" and payload["new_cost_per_lb"] == pytest.approx(2.30)
    coordinator.run(processed, POLICY_DECIDER)
    assert processed.execute("SELECT COUNT(*) FROM proposals WHERE event_id = ?", (event_id,)).fetchone()[0] > 0


def test_advisory_cannot_be_resolved_only_dismissed(processed):
    pid = processed.execute(
        "SELECT id FROM proposals WHERE kind = 'event_review' AND facts LIKE '%E15%'").fetchone()["id"]
    with pytest.raises(actions.ActionError, match="dismiss"):
        actions.resolve_review(processed, pid, "MAT-NBR-70")
    assert actions.dismiss_review(processed, pid)["status"] == "rejected"


def test_impact_without_history_row_matches_with_it(conn):
    change = {"material_id": "MAT-EPDM-70", "new_cost_per_lb": 2.27, "effective_date": "2026-11-01", "pct_change": 0.081}
    before_write = impact.affected_quotes(conn, change)
    conn.execute("INSERT INTO material_price_history (material_id, cost_per_lb, effective_date) VALUES (?, ?, ?)",
                 ("MAT-EPDM-70", 2.27, "2026-11-01"))
    after_write = impact.affected_quotes(conn, {k: v for k, v in change.items() if k != "new_cost_per_lb"})
    assert before_write == after_write


# ------------------------------------------------------------------ HTTP


@pytest.fixture
def client(processed, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", processed)
    with TestClient(api.app) as c:
        yield c


def test_overview_and_lanes(client):
    ov = client.get("/api/overview").json()
    decide = client.get("/api/queue", params={"lane": "decide"}).json()
    rules = client.get("/api/queue", params={"lane": "rules"}).json()
    assert ov["needs_you"] == len(decide) and ov["rule_pending"] == len(rules)
    assert all(p["decided_by"] != "rule" or p["kind"] == "event_review" for p in decide)
    quote_cards = [p for p in decide if p["kind"] == "quote_action"]
    assert quote_cards == sorted(quote_cards, key=lambda p: -p["exposure_usd"])


def test_inbox_shows_where_each_email_stands(client):
    mail = {m["id"]: m for m in client.get("/api/inbox").json()}
    assert mail["E07"]["review_status"] == "pending" and mail["E06"]["review_status"] is None
    assert mail["E01"]["quotes_checked"] > 0 and mail["E06"]["quotes_checked"] == 0

    review_id = next(p["id"] for p in client.get("/api/queue", params={"lane": "decide"}).json()
                     if p["kind"] == "event_review" and p["facts"]["email_id"] == "E15")
    client.post(f"/api/proposals/{review_id}/dismiss", json={})
    assert {m["id"]: m for m in client.get("/api/inbox").json()}["E15"]["review_status"] == "rejected"


def test_queue_filters_to_one_emails_cards(client):
    everything = client.get("/api/queue", params={"lane": "rules"}).json()
    e01 = client.get("/api/queue", params={"lane": "rules", "email": "E01"}).json()
    assert e01 and len(e01) < len(everything)
    assert all(p["event"]["material_id"] == "MAT-EPDM-70" for p in e01)
    inbox = {m["id"]: m for m in client.get("/api/inbox").json()}
    assert inbox["E01"]["rule_pending"] == len(e01)


def test_review_endpoint_and_errors(client):
    card = next(p for p in client.get("/api/queue", params={"lane": "decide"}).json() if p["action"] == "reprice")
    ok = client.post(f"/api/proposals/{card['id']}/review", json={"verdict": "approve"})
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    again = client.post(f"/api/proposals/{card['id']}/review", json={"verdict": "approve"})
    assert again.status_code == 400
    done = client.get("/api/queue", params={"lane": "done"}).json()
    assert [p["id"] for p in done] == [card["id"]]
