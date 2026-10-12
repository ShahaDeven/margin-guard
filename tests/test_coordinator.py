"""Coordinator, impact analysis and decision rules, with no API calls.

POLICY_DECIDER stands in for Claude by following the reference policy, so these
tests pin down the deterministic half; the live eval measures Claude's half.
"""

import json

import pytest
from test_pipeline import PERFECT_EXTRACTIONS

from evals.eval_decisions import draft_uses_proposed_prices
from evals.reference_policy import expected_action
from margin_guard import coordinator, impact, ingest
from margin_guard.decide import QuoteDecision, decide, rule_decision


def POLICY_DECIDER(facts):
    prices = " ".join(f"${ln['proposed_unit_price']:.4f}" for ln in facts["lines"])
    return QuoteDecision(action=expected_action(facts), confidence=0.9, rationale="reference policy",
                         email_subject="Revised quote", email_body=f"New prices: {prices}")


@pytest.fixture
def processed(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, POLICY_DECIDER)
    return conn


def _quote_proposals(conn):
    return [dict(r) | {"facts": json.loads(r["facts"])}
            for r in conn.execute("SELECT * FROM proposals WHERE kind = 'quote_action'")]


def test_every_event_is_processed(processed):
    statuses = {r["status"] for r in processed.execute("SELECT status FROM events")}
    assert statuses == {"processed"}


def test_every_affected_open_quote_gets_one_proposal(processed):
    for ev in processed.execute("SELECT id, payload FROM events WHERE event_type = 'price_change.detected'"
                                " AND source_ref LIKE 'email:%'"):
        p = json.loads(ev["payload"])
        got = {r["quote_id"] for r in processed.execute("SELECT quote_id FROM proposals WHERE event_id = ?", (ev["id"],))}
        expected = set() if p["pct_change"] <= 0 else set(impact.affected_quote_ids(processed, p["material_id"]))
        assert got == expected, p["material_id"]


def test_decisions_follow_policy(processed):
    proposals = _quote_proposals(processed)
    assert proposals
    for pr in proposals:
        assert pr["action"] == expected_action(pr["facts"]), pr["quote_id"]


def test_all_decision_paths_are_exercised(processed):
    # Guards the seed data: the demo needs every branch of the policy to show up.
    proposals = _quote_proposals(processed)
    rules = {p["rule_id"] for p in proposals if p["decided_by"] == "rule"}
    assert {"expires_before_change", "price_lock", "within_floor"} <= rules
    judgment = [p for p in proposals if p["decided_by"] == "llm"]
    assert {p["action"] for p in judgment} == {"reprice", "contact_customer"}
    assert len(judgment) >= 15, f"only {len(judgment)} judgment calls; the demo needs more"
    # At least one quote where a contract note overrides the size/tier rule.
    note_customers = {"C-02", "C-07", "C-12", "C-13"}
    assert note_customers & {p["facts"]["customer_id"] for p in judgment}


def test_overlapping_changes_supersede_older_cards(processed):
    rows = {p["id"]: p for p in _quote_proposals(processed)}
    superseded = [p for p in rows.values() if p["status"] == "superseded"]
    assert superseded, "expected quotes hit by more than one change (e.g. EPDM 70 + carbon black)"
    for old in superseded:
        new = rows[old["superseded_by"]]
        assert new["quote_id"] == old["quote_id"]
        assert new["status"] in ("pending", "superseded")   # a third change can replace it again
        assert new["event_id"] > old["event_id"]
        # The replacement covers the old change: it is priced on the stacked cost.
        assert new["facts"]["can_accept_after_change"]
        assert old["facts"]["effective_date"] <= new["facts"]["effective_date"]


def test_cards_left_side_by_side_each_cover_something(processed):
    by_quote: dict[str, list] = {}
    for p in _quote_proposals(processed):
        if p["status"] == "pending":
            by_quote.setdefault(p["quote_id"], []).append(p)
    for cards in by_quote.values():
        cards.sort(key=lambda p: p["id"])
        for older, newer in zip(cards, cards[1:]):
            # Kept only if the newer card can't stand in for the older one.
            assert (not newer["facts"]["can_accept_after_change"]
                    or older["facts"]["effective_date"] > newer["facts"]["effective_date"])


def test_expired_first_card_does_not_retire_a_reprice(conn):
    from margin_guard.coordinator import supersede_older
    quote_id = conn.execute("SELECT id FROM quotes WHERE status = 'open' LIMIT 1").fetchone()[0]
    facts = {"quote_id": quote_id, "effective_date": "2026-11-01", "can_accept_after_change": True}
    event_id = conn.execute("INSERT INTO events (event_type, idempotency_key, payload)"
                            " VALUES ('price_change.detected', 'k1', '{}')").lastrowid
    insert = ("INSERT INTO proposals (idempotency_key, event_id, quote_id, kind, action, decided_by, rationale, facts)"
              " VALUES (?, ?, ?, 'quote_action', ?, 'rule', 'r', ?)")
    conn.execute(insert, ("old", event_id, quote_id, "reprice", json.dumps(facts)))
    new_id = conn.execute(insert, ("new", event_id, quote_id, "honor", "{}")).lastrowid
    # A later change the quote expires before: its "honor" card must not retire the reprice.
    later = facts | {"effective_date": "2026-11-15", "can_accept_after_change": False}
    assert supersede_older(conn, new_id, later) == 0
    # A later change the quote is still open for: it covers the Nov 1 card.
    still_open = facts | {"effective_date": "2026-11-15"}
    assert supersede_older(conn, new_id, still_open) == 1
    assert conn.execute("SELECT status FROM proposals WHERE idempotency_key = 'old'").fetchone()[0] == "superseded"


def test_rerun_is_a_no_op(processed):
    before = processed.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    assert coordinator.run(processed, POLICY_DECIDER) == {}
    assert processed.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == before


def test_cost_decrease_makes_no_proposals(processed):
    ev = processed.execute(
        "SELECT id, result FROM events WHERE payload LIKE '%MAT-CR-60%' AND source_ref = 'email:E05'").fetchone()
    assert processed.execute("SELECT COUNT(*) FROM proposals WHERE event_id = ?", (ev["id"],)).fetchone()[0] == 0
    assert "decrease" in json.loads(ev["result"])["note"]


def test_review_events_become_review_items(processed):
    items = processed.execute("SELECT facts FROM proposals WHERE kind = 'event_review'").fetchall()
    assert sorted(json.loads(r["facts"])["email_id"] for r in items) == ["E07", "E15"]


def test_price_change_is_recorded_in_history(processed):
    row = processed.execute(
        "SELECT cost_per_lb, source_event_id FROM material_price_history"
        " WHERE material_id = 'MAT-EPDM-70' AND effective_date = '2026-11-01'").fetchone()
    assert row["cost_per_lb"] == pytest.approx(2.27) and row["source_event_id"] is not None
    # Future-dated, so today's catalog cost is unchanged.
    assert processed.execute("SELECT cost_per_lb FROM materials WHERE id = 'MAT-EPDM-70'").fetchone()[0] == 2.10


def test_decider_failure_escalates_instead_of_crashing(conn):
    def broken(_):
        raise RuntimeError("api down")
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, broken)
    assert {r["status"] for r in conn.execute("SELECT status FROM events")} == {"processed"}
    escalated = conn.execute("SELECT COUNT(*) FROM proposals WHERE action = 'escalate'").fetchone()[0]
    assert escalated > 0


# ------------------------------------------------------------------ impact


def _record(conn, material_id, cost, effective):
    conn.execute("INSERT INTO material_price_history (material_id, cost_per_lb, effective_date) VALUES (?, ?, ?)",
                 (material_id, cost, effective))


def test_impact_math_on_a_single_material_part(conn):
    _record(conn, "MAT-EPDM-70", 2.27, "2026-11-01")
    change = {"material_id": "MAT-EPDM-70", "effective_date": "2026-11-01", "pct_change": 0.081}
    checked = 0
    for facts in impact.affected_quotes(conn, change):
        for ln in facts["lines"]:
            if ln["part_id"] != "P-1001":       # 0.42 lb EPDM 70, 6% scrap, nothing else
                continue
            assert ln["unit_cost_after"] - ln["unit_cost_before"] == pytest.approx(0.42 * 1.06 * 0.17, abs=2e-4)
            old_margin = 1 - ln["unit_cost_before"] / ln["unit_price"]
            new_margin = 1 - ln["unit_cost_after"] / ln["proposed_unit_price"]
            assert new_margin == pytest.approx(old_margin, abs=1e-3)
            checked += 1
    assert checked, "expected an open quote containing P-1001"


def test_quote_that_expires_first_has_no_exposure(conn):
    _record(conn, "MAT-EPDM-70", 2.27, "2026-11-01")
    change = {"material_id": "MAT-EPDM-70", "effective_date": "2026-11-01", "pct_change": 0.081}
    for facts in impact.affected_quotes(conn, change):
        if facts["valid_until"] < "2026-11-01":
            assert not facts["can_accept_after_change"] and facts["exposure_usd"] == 0
        else:
            assert facts["exposure_usd"] > 0


def test_changes_on_the_same_part_stack(conn):
    # P-1004 uses EPDM 70 and carbon black; both rise Nov 1.
    _record(conn, "MAT-EPDM-70", 2.27, "2026-11-01")
    _record(conn, "MAT-CB-N550", 1.18, "2026-11-01")
    change = {"material_id": "MAT-CB-N550", "effective_date": "2026-11-01", "pct_change": 0.083}
    lines = [ln for f in impact.affected_quotes(conn, change) for ln in f["lines"] if ln["part_id"] == "P-1004"]
    assert lines
    for ln in lines:
        both = 1.10 * 1.05 * 0.17 + 0.12 * 1.0 * 0.09
        assert ln["unit_cost_after"] - ln["unit_cost_before"] == pytest.approx(both, abs=2e-4)


# ------------------------------------------------------------------ rules


def _facts(**over):
    base = {"quote_id": "Q-T", "customer_id": "C-03", "customer_name": "Test Co", "customer_tier": "standard",
            "price_lock_until": None, "contract_note": None, "valid_until": "2026-12-31",
            "effective_date": "2026-11-01", "can_accept_after_change": True, "margin_floor": 0.20,
            "margin_before": 0.24, "margin_after": 0.22, "exposure_usd": 500.0, "quote_value_usd": 5000.0,
            "material_id": "MAT-X", "lines": []}
    return base | over


def test_rule_expires_first():
    f = _facts(valid_until="2026-10-30", can_accept_after_change=False)
    assert rule_decision(f)[:2] == ("honor", "expires_before_change")


def test_rule_price_lock_beats_floor():
    f = _facts(price_lock_until="2026-12-31", margin_after=0.15)
    assert rule_decision(f)[:2] == ("honor", "price_lock")


def test_rule_lock_that_ends_before_change_does_not_apply():
    f = _facts(price_lock_until="2026-10-31", margin_after=0.15)
    assert rule_decision(f) is None


def test_rule_within_floor_absorbs():
    assert rule_decision(_facts())[:2] == ("absorb", "within_floor")


def test_below_floor_goes_to_the_decider():
    calls = []

    def spy(facts):
        calls.append(facts["quote_id"])
        return POLICY_DECIDER(facts)
    pr = decide(_facts(margin_after=0.18), spy)
    assert calls == ["Q-T"] and pr["decided_by"] == "llm" and pr["action"] == "reprice"


def test_draft_price_check():
    facts = _facts(lines=[{"unit_price": 3.10, "proposed_unit_price": 3.1842},
                          {"unit_price": 1.00, "proposed_unit_price": 1.00}])
    assert draft_uses_proposed_prices(facts, "Brackets: $3.18 each")
    assert not draft_uses_proposed_prices(facts, "Brackets: $3.25 each")
    assert not draft_uses_proposed_prices(facts, None)
