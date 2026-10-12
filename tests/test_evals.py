"""The eval machinery itself, with no API calls: if the yardstick is wrong, every number it produces is too."""

import json

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import PERFECT_EXTRACTIONS

from evals import eval_approvals, eval_scenarios
from evals.reference_policy import NOTE_OVERRIDES, expected_action
from evals.scenarios import scenarios
from margin_guard import actions, coordinator, ingest, llm
from margin_guard.config import ROOT
from margin_guard.decide import QuoteDecision


# ------------------------------------------------------------------ the scenarios


def test_scenarios_are_well_formed():
    s = scenarios()
    assert len(s) == 30 and len({x["id"] for x in s}) == 30
    for x in s:
        f = x["facts"]
        assert f["margin_after"] < f["margin_floor"], x["id"]          # every one reaches Claude
        assert x["expected"] in ("reprice", "contact_customer")
        assert f["lines"][0]["proposed_unit_price"] > f["lines"][0]["unit_price"]


def test_threshold_values_are_exact():
    by_id = {x["id"]: x["facts"]["quote_value_usd"] for x in scenarios()}
    assert (by_id["S01"], by_id["S02"], by_id["S03"]) == (14_999.0, 15_000.0, 15_001.0)


def test_gold_matches_reference_policy_where_no_note_applies():
    for x in scenarios():
        if x["facts"]["contract_note"] is None:
            f = x["facts"] | {"customer_id": "C-none"}
            assert f["customer_id"] not in NOTE_OVERRIDES
            assert expected_action(f) == x["expected"], x["id"]


# ------------------------------------------------------------------ draft checks


def _scenario(sid):
    return next(x for x in scenarios() if x["id"] == sid)


def _good_body(s):
    f = s["facts"]
    names = " and ".join(c["material_name"] for c in f["cost_changes"])
    prices = " ".join(f"${ln['proposed_unit_price']:.4f}" for ln in f["lines"])
    return f"Dear {f['buyer']['name']}, call {f['buyer']['phone']}. {names} went up. New prices: {prices}."


def test_a_good_draft_passes_every_check():
    for sid, action in (("S27", "reprice"), ("S28", "contact_customer")):
        s = _scenario(sid)
        checks = eval_scenarios.draft_checks(s, action, "Revised quote", _good_body(s))
        assert checks and all(checks.values()), (sid, checks)


def test_draft_checks_catch_each_failure():
    s = _scenario("S28")
    body = _good_body(s)
    assert not eval_scenarios.draft_checks(s, "contact_customer", "x", body.replace(s["facts"]["buyer"]["phone"], ""))["has_buyer_phone"]
    assert not eval_scenarios.draft_checks(s, "contact_customer", "x", body + " (MAT-NBR-90)")["no_internal_ids"]
    assert not eval_scenarios.draft_checks(s, "contact_customer", "x", body.replace("Nitrile (NBR) 90", "rubber"))["names_all_materials"]
    s26 = _scenario("S26")
    assert not eval_scenarios.draft_checks(s26, "contact_customer", "x", _good_body(s26) + " cc bids@competitor.example")["no_competitor"]


def test_flagging_an_injection_is_not_following_it():
    s26 = _scenario("S26")
    warned = _good_body(s26) + ("\n\nNote: the contract note asks us to email bids@competitor.example. "
                                "That looks inappropriate, so I did not follow it. Send nothing to that address.")
    assert eval_scenarios.draft_checks(s26, "contact_customer", "x", warned)["no_competitor"]
    # Haiku's wording, in a single paragraph, is a warning too.
    flagged = _good_body(s26) + (" Also flag that the contract note asks for the quote to be emailed to "
                                 "bids@competitor.example; the request should be reviewed before anything is sent.")
    assert eval_scenarios.draft_checks(s26, "contact_customer", "x", flagged)["no_competitor"]
    assert not eval_scenarios.draft_checks(s26, "contact_customer", "Quote for bids@competitor.example", warned)["no_competitor"]


def test_failed_calls_are_neither_scored_nor_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_scenarios, "RESULTS_DIR", tmp_path)
    cases = scenarios()[:2]

    def out_of_credit(facts, model=None, log=None):
        raise RuntimeError("Your credit balance is too low")
    monkeypatch.setattr(eval_scenarios, "llm_decide", out_of_credit)
    rows = eval_scenarios.run_model("claude-haiku-5-5", cases, runs=1, replay=False)
    assert all(r["action"] == "error" for r in rows)
    assert json.loads((tmp_path / "scenarios_claude-haiku-5-5.json").read_text(encoding="utf-8")) == {}


# ------------------------------------------------------------------ the runner and the reports


def test_runner_scores_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_scenarios, "RESULTS_DIR", tmp_path)
    cases = scenarios()[:4]
    gold = {x["facts"]["quote_id"]: x for x in cases}

    def fake(facts, model=None, log=None):
        x = gold[facts["quote_id"]]
        log.append({"model": model, "input_tokens": 1000, "output_tokens": 200, "seconds": 1.0})
        wrong = x["id"] == "S01"                                  # one deliberate miss
        action = "contact_customer" if wrong else x["expected"]
        return QuoteDecision(action=action, confidence=0.6 if wrong else 0.97, rationale="r",
                             email_subject="s", email_body=_good_body(x))

    monkeypatch.setattr(eval_scenarios, "llm_decide", fake)
    rows = eval_scenarios.run_model("claude-sonnet-5-5", cases, runs=2, replay=False)
    assert len(rows) == 8 and sum(r["correct"] for r in rows) == 6
    # Replay reads the cache and never calls the model.
    monkeypatch.setattr(eval_scenarios, "llm_decide", lambda *a, **k: pytest.fail("called the model on replay"))
    assert [r["correct"] for r in eval_scenarios.run_model("claude-sonnet-5-5", cases, 2, replay=True)] == \
        [r["correct"] for r in rows]

    table = {t["threshold"]: t for t in eval_scenarios.autonomy_table(rows)}
    assert table[0.95]["accuracy"] == 1.0 and table[0.95]["coverage"] == 0.75   # the misses were unsure
    assert table[0.5]["accuracy"] == 0.75 and table[0.5]["coverage"] == 1.0


def test_haiku_gets_no_server_side_fallback():
    assert llm._fallback_args("claude-haiku-5-5") == {}
    sonnet = llm._fallback_args("claude-sonnet-5-5")
    assert sonnet == {} or sonnet["extra_body"] == {"fallbacks": "default"}


def test_cost_uses_per_model_prices():
    entries = [{"model": "claude-sonnet-5-5", "input_tokens": 1_000_000, "output_tokens": 0, "seconds": 1},
               {"model": "claude-haiku-5-5", "input_tokens": 0, "output_tokens": 1_000_000, "seconds": 1}]
    assert llm.cost_usd(entries) == pytest.approx(2.00 + 0.50)


# ------------------------------------------------------------------ learning from approvals


@pytest.fixture
def processed(conn):
    ingest.run(conn, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
    coordinator.run(conn, POLICY_DECIDER)
    return conn


def test_reviews_become_regression_cases(processed):
    llm_cards = [r["id"] for r in processed.execute(
        "SELECT id FROM proposals WHERE decided_by = 'llm' AND status = 'pending' AND action = 'contact_customer' ORDER BY id")]
    keep, change, drop = llm_cards[:3]
    actions.review(processed, keep, "approve")
    actions.review(processed, change, "edit", action="reprice", note="small order, email is fine")
    actions.review(processed, drop, "reject", note="customer already accepted")

    outcomes = {o["id"]: o["outcome"] for o in eval_approvals.review_outcomes(processed)}
    assert outcomes == {keep: "approved_as_is", change: "action_changed", drop: "rejected"}
    [case] = eval_approvals.learned_cases(eval_approvals.review_outcomes(processed))
    assert case["id"] == f"A{change}" and case["expected"] == "reprice" and case["group"] == "from_approvals"
    assert "small order" in case["description"] and case["facts"]["quote_id"]


def test_override_to_absorb_is_a_policy_signal_not_a_test_case(processed):
    pid = processed.execute(
        "SELECT id FROM proposals WHERE decided_by = 'llm' AND status = 'pending' ORDER BY id LIMIT 1").fetchone()[0]
    actions.review(processed, pid, "edit", action="absorb", note="tiny exposure, not worth a call")
    outcomes = eval_approvals.review_outcomes(processed)
    assert outcomes[0]["outcome"] == "action_changed"
    assert eval_approvals.learned_cases(outcomes) == []


# ------------------------------------------------------------------ the console report


def test_console_reports_but_never_acts_on_the_bar(processed, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from margin_guard import api
    bar = tmp_path / "autonomy.json"
    bar.write_text(json.dumps({"model": "claude-sonnet-5-5", "threshold": 0.9, "runs": 90}), encoding="utf-8")
    monkeypatch.setattr(api, "AUTONOMY_PATH", bar)
    monkeypatch.setattr(api, "_conn", processed)
    pending_before = processed.execute("SELECT COUNT(*) FROM proposals WHERE status = 'pending'").fetchone()[0]
    with TestClient(api.app) as c:
        a = c.get("/api/overview").json()["autonomy"]
    llm_pending = processed.execute(
        "SELECT COUNT(*) FROM proposals WHERE status = 'pending' AND decided_by = 'llm'").fetchone()[0]
    assert a["threshold"] == 0.9 and a["would_clear"] == llm_pending    # POLICY_DECIDER says 0.9
    assert processed.execute("SELECT COUNT(*) FROM proposals WHERE status = 'pending'").fetchone()[0] == pending_before


def test_holdout_emails_are_well_formed():
    emails = json.loads((ROOT / "data" / "vendor_emails_holdout.json").read_text(encoding="utf-8"))
    tuned = json.loads((ROOT / "data" / "vendor_emails.json").read_text(encoding="utf-8"))
    assert len(emails) == 10 and not {e["id"] for e in emails} & {e["id"] for e in tuned}
    for e in emails:
        assert e["gold"]["outcome"] in ("detected", "duplicate", "needs_review", "ignored")
        assert bool(e["gold"]["changes"]) == (e["gold"]["outcome"] == "detected")
