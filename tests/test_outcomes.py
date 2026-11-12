"""Customer responses to an increase: accepted, negotiated, lost; undo; the owner's figures; the record on cards."""

import json

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import PERFECT_EXTRACTIONS

from margin_guard import actions, coordinator, ingest, leakage, outcomes
from margin_guard.money import D


@pytest.fixture
def processed(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, POLICY_DECIDER)
    return conn


def _approved(conn, action: str) -> int:
    pid = conn.execute("SELECT id FROM proposals WHERE status = 'pending' AND kind = 'quote_action' AND action = ?"
                       " ORDER BY exposure_usd DESC, id LIMIT 1", (action,)).fetchone()["id"]
    actions.review(conn, pid, "approve")
    return pid


def _facts(conn, pid):
    return json.loads(conn.execute("SELECT facts FROM proposals WHERE id = ?", (pid,)).fetchone()["facts"])


def _prices(conn, quote_id):
    return {r["id"]: r["unit_price"] for r in conn.execute("SELECT id, unit_price FROM quote_lines WHERE quote_id = ?",
                                                           (quote_id,))}


def _console(conn):
    return conn.execute("SELECT COUNT(*) FROM quote_outcomes WHERE source = 'console'").fetchone()[0]


# ------------------------------------------------------------------ recording


def test_accepted_reprice_keeps_the_prices_already_written(processed):
    pid = _approved(processed, "reprice")
    f = _facts(processed, pid)
    before = _prices(processed, f["quote_id"])
    o = outcomes.record(processed, pid, "accepted")
    assert o["recovered_usd"] == o["asked_usd"] == float(outcomes.asked(f)) > 0
    assert o["channel"] == "email" and o["price_changes"] == []
    assert _prices(processed, f["quote_id"]) == before


def test_accepted_call_writes_the_proposed_prices(processed):
    pid = _approved(processed, "contact_customer")
    f = _facts(processed, pid)
    o = outcomes.record(processed, pid, "accepted")
    now = _prices(processed, f["quote_id"])
    assert o["channel"] == "call" and o["price_changes"]
    assert all(now[ln["line_id"]] == ln["proposed_unit_price"] for ln in f["lines"])


def test_negotiated_moves_each_line_by_the_same_share(processed):
    pid = _approved(processed, "reprice")
    f = _facts(processed, pid)
    ask = outcomes.asked(f)
    o = outcomes.record(processed, pid, "negotiated", recovered_usd=str(ask / 2))
    now = _prices(processed, f["quote_id"])
    for ln in f["lines"]:
        expected = D(ln["unit_price"]) + (D(ln["proposed_unit_price"]) - D(ln["unit_price"])) / 2
        assert D(now[ln["line_id"]]) == pytest.approx(expected, abs=D("0.0001"))
    # What's recorded is what the agreed unit prices bring in, to the cent.
    assert o["recovered_usd"] == pytest.approx(float(ask / 2), abs=0.05)


@pytest.mark.parametrize("amount, message", [(None, "say how much"), ("0", "more than \\$0"), ("1e9", "less than"),
                                             ("abc", "not an amount")])
def test_negotiated_needs_a_sensible_amount(processed, amount, message):
    pid = _approved(processed, "reprice")
    with pytest.raises(outcomes.OutcomeError, match=message):
        outcomes.record(processed, pid, "negotiated", recovered_usd=amount)
    assert _console(processed) == 0


def test_lost_marks_the_quote_lost_and_counts_its_value(processed):
    pid = _approved(processed, "contact_customer")
    f = _facts(processed, pid)
    o = outcomes.record(processed, pid, "lost", on="2026-10-20", note="went with a cheaper shop")
    assert processed.execute("SELECT status FROM quotes WHERE id = ?", (f["quote_id"],)).fetchone()[0] == "lost"
    assert o["lost_revenue_usd"] == pytest.approx(f["quote_value_usd"], abs=0.01)
    assert o["recovered_usd"] == 0 and o["outcome_date"] == "2026-10-20"


def test_only_approved_customer_facing_decisions(processed):
    pending = processed.execute("SELECT id FROM proposals WHERE status = 'pending' AND action = 'reprice'"
                                " LIMIT 1").fetchone()["id"]
    with pytest.raises(outcomes.OutcomeError, match="approved"):
        outcomes.record(processed, pending, "accepted")
    honor = processed.execute("SELECT id FROM proposals WHERE status = 'pending' AND action = 'honor'"
                              " LIMIT 1").fetchone()["id"]
    actions.review(processed, honor, "approve")
    with pytest.raises(outcomes.OutcomeError, match="reprice or a call"):
        outcomes.record(processed, honor, "accepted")


def test_one_response_per_decision_and_dates_checked(processed):
    pid = _approved(processed, "reprice")
    with pytest.raises(outcomes.OutcomeError, match="not a date"):
        outcomes.record(processed, pid, "accepted", on="next week")
    outcomes.record(processed, pid, "accepted")
    with pytest.raises(outcomes.OutcomeError, match="already has"):
        outcomes.record(processed, pid, "lost")


def test_refuses_when_the_quote_changed_since(processed):
    pid = _approved(processed, "reprice")
    f = _facts(processed, pid)
    processed.execute("UPDATE quote_lines SET unit_price = unit_price + 1 WHERE id = ?", (f["lines"][0]["line_id"],))
    with pytest.raises(outcomes.OutcomeError, match="revised since"):
        outcomes.record(processed, pid, "accepted")


# ------------------------------------------------------------------ undo


def test_undo_restores_prices_and_status(processed):
    call = _approved(processed, "contact_customer")
    f = _facts(processed, call)
    before = _prices(processed, f["quote_id"])
    outcomes.undo(processed, outcomes.record(processed, call, "negotiated", recovered_usd="1.00")["id"])
    assert _prices(processed, f["quote_id"]) == before

    outcomes.undo(processed, outcomes.record(processed, call, "lost")["id"])
    assert processed.execute("SELECT status FROM quotes WHERE id = ?", (f["quote_id"],)).fetchone()[0] == "open"
    assert _console(processed) == 0


def test_decision_undo_waits_for_the_response_undo(processed):
    pid = _approved(processed, "reprice")
    o = outcomes.record(processed, pid, "accepted")
    with pytest.raises(actions.ActionError, match="customer's response"):
        actions.reopen(processed, pid)
    outcomes.undo(processed, o["id"])
    assert actions.reopen(processed, pid)["status"] == "pending"


def test_history_cannot_be_undone(conn):
    hid = conn.execute("SELECT id FROM quote_outcomes WHERE source = 'history' LIMIT 1").fetchone()["id"]
    with pytest.raises(outcomes.OutcomeError, match="history"):
        outcomes.undo(conn, hid)


# ------------------------------------------------------------------ figures and records


def test_seeded_history_is_coherent_and_moves_nothing_else(conn):
    rows = conn.execute("SELECT o.*, q.status FROM quote_outcomes o JOIN quotes q ON q.id = o.quote_id").fetchall()
    assert len(rows) > 20 and all(r["source"] == "history" and r["proposal_id"] is None for r in rows)
    assert all(r["status"] == "lost" for r in rows if r["outcome"] == "lost")
    assert all(r["status"] == "won" for r in rows if r["outcome"] != "lost")
    assert all(0 < r["recovered_usd"] < r["asked_usd"] for r in rows if r["outcome"] == "negotiated")
    assert leakage.analyze(conn)["leaked_usd"] == pytest.approx(6151, abs=1)     # the leakage figures don't move


def test_kept_counts_only_jobs_the_customer_stayed_on(processed):
    a = _approved(processed, "reprice")
    b = _approved(processed, "contact_customer")
    outcomes.record(processed, a, "accepted")
    outcomes.record(processed, b, "lost")
    t = outcomes.summary(processed)["console"]
    assert (t["requests"], t["accepted"], t["lost"]) == (2, 1, 1)
    assert t["kept"] == 1.0 and t["recovered_usd"] == t["asked_kept_jobs_usd"]
    assert t["lost_revenue_usd"] > 0


def test_awaiting_lists_approved_asks_without_a_response(processed):
    a = _approved(processed, "reprice")
    b = _approved(processed, "contact_customer")
    assert {w["proposal_id"] for w in outcomes.summary(processed)["awaiting"]} == {a, b}
    outcomes.record(processed, a, "accepted")
    assert [w["proposal_id"] for w in outcomes.summary(processed)["awaiting"]] == [b]


@pytest.mark.parametrize("counts, expected", [
    ({"requests": 1, "accepted": 1, "negotiated": 0, "lost": 0}, "too few increases to say"),
    ({"requests": 3, "accepted": 2, "negotiated": 0, "lost": 1}, "has walked over increases"),
    ({"requests": 4, "accepted": 2, "negotiated": 2, "lost": 0}, "usually pushes back"),
    ({"requests": 4, "accepted": 3, "negotiated": 1, "lost": 0}, "usually accepts"),
])
def test_pattern(counts, expected):
    assert outcomes.pattern(counts) == expected


# ------------------------------------------------------------------ HTTP


@pytest.fixture
def client(processed, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    monkeypatch.setattr(api, "_conn", processed)
    with TestClient(api.app) as c:
        yield c


def test_outcomes_over_http(client, processed):
    pid = _approved(processed, "reprice")
    assert client.get("/api/overview").json()["awaiting_reply"] == 1
    done = {p["id"]: p for p in client.get("/api/queue", params={"lane": "done"}).json()}
    assert done[pid]["outcome"] is None and "customer_record" in done[pid]

    bad = client.post(f"/api/proposals/{pid}/outcome", json={"outcome": "negotiated"})
    assert bad.status_code == 400 and "say how much" in bad.json()["detail"]
    o = client.post(f"/api/proposals/{pid}/outcome", json={"outcome": "accepted"}).json()
    done = {p["id"]: p for p in client.get("/api/queue", params={"lane": "done"}).json()}
    assert done[pid]["outcome"]["id"] == o["id"]
    assert client.get("/api/outcomes").json()["console"]["accepted"] == 1

    assert client.post(f"/api/outcomes/{o['id']}/undo").json()["undone"] is True
    assert client.get("/api/overview").json()["awaiting_reply"] == 1
