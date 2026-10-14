"""Promotion gate: statistics, answer keys, the gate's labels and verdicts, and the replay cache. No API calls."""

import json
from types import SimpleNamespace

import pytest

from evals.promotion import replay, review_shop
from evals.promotion.candidates import BASELINE, CANDIDATES, de_minimis_key
from evals.promotion.cases import replay_cases
from evals.promotion.gate import gate, naive_gate
from evals.promotion.stats import benjamini_hochberg, fisher_exact, paired_bootstrap, wilson
from evals.reference_policy import expected_action
from evals.scenarios import scenarios
from margin_guard import db, llm, seed
from margin_guard.decide import SYSTEM_PROMPT, QuoteDecision, QuoteDecisionWithAbsorb, decide, llm_decide, system_prompt


def _scenario(sid):
    return next(s for s in scenarios() if s["id"] == sid)


# --- statistics -------------------------------------------------------------

def test_fisher_matches_known_values():
    assert fisher_exact(10, 0, 7, 3) == pytest.approx(0.2105, abs=1e-4)    # 10/10 vs 7/10: not significant
    assert fisher_exact(10, 0, 0, 10) == pytest.approx(1.0825e-5, rel=1e-3)
    assert fisher_exact(1, 0, 0, 1) == 1.0                                 # K=1 can never be significant
    assert fisher_exact(3, 1, 1, 3) == pytest.approx(0.4857, abs=1e-4)


def test_wilson_and_bh():
    lo, hi = wilson(7, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.397, 0.892)
    assert wilson(0, 0) == (0.0, 1.0)
    assert [round(p, 3) for p in benjamini_hochberg([0.01, 0.04, 0.03, 0.2])] == [0.04, 0.053, 0.053, 0.2]


def test_paired_bootstrap_brackets_the_mean():
    mean, lo, hi = paired_bootstrap([0.0, -0.1, 0.0, 0.2, 0.1])
    assert lo <= mean <= hi and mean == pytest.approx(0.04)


# --- candidates and the decide refactor ------------------------------------

def test_baseline_prompt_is_the_console_prompt():
    assert system_prompt(BASELINE.policy) == SYSTEM_PROMPT


def test_candidate_policies_differ_only_where_intended():
    base = BASELINE.policy
    for cid in ("C1b", "C2", "C3a", "C3b"):
        assert CANDIDATES[cid].policy != base
    assert "override" not in CANDIDATES["C3b"].policy
    assert "$50" in CANDIDATES["C1b"].policy


def test_de_minimis_key_and_targets():
    s12 = _scenario("S12")                           # $800 quote, ~$28 at risk, must-call note
    assert s12["expected"] == "contact_customer"
    assert de_minimis_key(s12) == "absorb"
    cases = replay_cases()
    assert len(cases) == 62
    targets = CANDIDATES["C1a"].targets(cases)
    assert "S12" in targets and all(c["facts"]["exposure_usd"] < 50 for c in cases if c["id"] in targets)
    assert CANDIDATES["C2"].targets(cases) == ["S24"]
    assert CANDIDATES["C3a"].targets(cases) == [] and BASELINE.targets(cases) == []


def test_cases_carry_the_right_baseline_answer():
    by_id = {c["id"]: c for c in replay_cases()}
    for s in scenarios():                            # hand-written gold, not the reference table
        assert by_id[s["id"]]["expected"] == s["expected"]
    assert by_id["S24"]["expected"] == "reprice" and by_id["S12"]["expected"] == "contact_customer"
    shop = [c for c in by_id.values() if c["group"] == "shop"]
    assert len(shop) == 32 and all(c["expected"] == expected_action(c["facts"]) for c in shop)


def test_de_minimis_rule_settles_without_the_model():
    cand = CANDIDATES["C1a"]
    p = decide(_scenario("S12")["facts"], lambda f: pytest.fail("called the model"), cand.extra_rules)
    assert (p["action"], p["decided_by"], p["rule_id"]) == ("absorb", "rule", "de_minimis")
    big = _scenario("S05")["facts"]                  # $60k: well over the line, goes to the decider
    called = []
    decide(big, lambda f: called.append(1) or QuoteDecision(
        action="contact_customer", confidence=0.9, rationale="r", email_subject="s", email_body="b"), cand.extra_rules)
    assert called


def test_llm_decide_passes_candidate_policy_and_schema(monkeypatch):
    seen = {}

    def fake_parse(system, user, schema, **kw):
        seen.update(system=system, schema=schema)
        return schema(action="absorb" if schema is QuoteDecisionWithAbsorb else "reprice",
                      confidence=0.9, rationale="r", email_subject="s", email_body="b")

    monkeypatch.setattr(llm, "parse", fake_parse)
    llm_decide(_scenario("S01")["facts"])
    assert seen["system"] == SYSTEM_PROMPT and seen["schema"] is QuoteDecision
    d = llm_decide(_scenario("S01")["facts"], policy=CANDIDATES["C1b"].policy, allow_absorb=True)
    assert "$50" in seen["system"] and d.action == "absorb"


# --- the gate ---------------------------------------------------------------

def _cases(n):
    s = _scenario("S04")                              # standard, $2,000, no note: gold reprice
    return [{"id": f"X{i}", "facts": s["facts"], "expected": s["expected"]} for i in range(n)]


def _acts(right, n, want="reprice", wrong="contact_customer"):
    return [want] * right + [wrong] * (n - right)


def test_gate_labels_and_verdicts():
    cases = _cases(4)
    base = {"X0": _acts(10, 10), "X1": _acts(10, 10), "X2": _acts(7, 10), "X3": _acts(0, 10)}
    clean = {"X0": _acts(10, 10), "X1": _acts(10, 10), "X2": _acts(8, 10), "X3": _acts(0, 10)}
    res = gate(BASELINE, cases, base, clean)
    assert [r.label for r in res.rows] == ["stable_pass", "stable_pass", "flaky", "stable_fail"]
    assert res.verdict == "promote"

    broken = {**clean, "X1": _acts(0, 10)}
    res = gate(BASELINE, cases, base, broken)
    assert res.rows[1].label == "regressed" and res.verdict == "reject"

    wobbly = {**clean, "X2": _acts(4, 10)}           # 7/10 -> 4/10 on a case already flaky in the baseline
    assert gate(BASELINE, cases, base, wobbly, version=1).verdict == "hold"    # v1: any big drop holds
    res = gate(BASELINE, cases, base, wobbly)
    assert res.rows[2].label == "flaky" and res.verdict == "promote"           # v2: noise needs significance

    dipped = {**clean, "X1": _acts(7, 10)}           # 10/10 -> 7/10 on a case that was stable
    assert gate(BASELINE, cases, base, dipped).verdict == "hold"
    assert gate(BASELINE, cases, base, dipped, known_flaky=frozenset({"X1"})).verdict == "promote"


def test_gate_requires_targets_fixed():
    cases = replay_cases()
    cand = CANDIDATES["C2"]
    base = {c["id"]: [cand.key(c)] * 10 for c in cases}
    base["S24"] = ["contact_customer"] * 10
    fixed = dict(base, S24=["reprice"] * 10)
    assert gate(cand, cases, base, fixed).verdict == "promote"
    partly = dict(base, S24=["reprice"] * 4 + ["contact_customer"] * 6)
    res = gate(cand, cases, base, partly)
    assert res.verdict == "hold" and any("S24" in r for r in res.reasons)


def test_naive_gate_calls_noise_a_regression_at_k1():
    cases = _cases(2)
    base = {"X0": ["reprice"], "X1": ["reprice"]}
    flip = {"X0": ["reprice"], "X1": ["contact_customer"]}     # one flaky case flipped, nothing changed
    assert naive_gate(BASELINE, cases, base, flip).verdict == "reject"
    assert gate(BASELINE, cases, base, flip).verdict == "hold"


# --- replay cache -----------------------------------------------------------

def test_replay_caches_and_reruns_only_what_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "OUT_DIR", tmp_path)
    calls = []
    gold = {s["facts"]["quote_id"]: s["expected"] for s in scenarios()}

    def fake(facts, model=None, log=None, *, policy=None, allow_absorb=False):
        calls.append(facts["quote_id"])
        prices = " ".join(f"${ln['proposed_unit_price']:.4f}" for ln in facts["lines"])
        return QuoteDecision(action=gold[facts["quote_id"]], confidence=0.9, rationale="r",
                             email_subject="s", email_body=f"Hi Jordan, new prices: {prices}")

    monkeypatch.setattr(replay, "llm_decide", fake)
    cases = [_scenario("S01"), _scenario("S12")]
    replay.run_candidate(BASELINE, cases, k=3)
    assert len(calls) == 6
    replay.run_candidate(BASELINE, cases, k=3)
    assert len(calls) == 6                            # all cached
    replay.run_candidate(BASELINE, cases, k=4)
    assert len(calls) == 8                            # only the new replay index

    out = replay.outcomes(BASELINE, cases, k=4)
    assert out == {"S01": ["reprice"] * 4, "S12": ["contact_customer"] * 4}

    # C1a settles S12 by rule: one model call per replay for S01 only
    replay.run_candidate(CANDIDATES["C1a"], cases, k=2)
    assert len(calls) == 10
    assert replay.outcomes(CANDIDATES["C1a"], cases, k=2)["S12"] == ["absorb", "absorb"]


def test_replay_failed_calls_are_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "OUT_DIR", tmp_path)

    def broken(*a, **k):
        raise RuntimeError("out of credit")

    monkeypatch.setattr(replay, "llm_decide", broken)
    replay.run_candidate(BASELINE, [_scenario("S01")], k=2)
    assert replay.load_cache("C0") == {}
    assert replay.outcomes(BASELINE, [_scenario("S01")], k=2) == {"S01": []}


# --- review shops -----------------------------------------------------------

def test_seed_variants_build_different_shops(tmp_path):
    a, b = db.connect(tmp_path / "a.db"), db.connect(tmp_path / "b.db")
    seed.build(a)
    seed.build(b, rng_seed=43)
    qa = [tuple(r) for r in a.execute("SELECT customer_id, issued_date FROM quotes ORDER BY id")]
    qb = [tuple(r) for r in b.execute("SELECT customer_id, issued_date FROM quotes ORDER BY id")]
    assert qa != qb
    assert a.execute("SELECT COUNT(*) FROM customers").fetchone() == b.execute("SELECT COUNT(*) FROM customers").fetchone()


def test_review_export_reads_reviewed_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(review_shop, "SHOPS_DIR", tmp_path)
    monkeypatch.setattr(review_shop, "EXPORT", tmp_path / "reviews.json")
    conn = db.connect(tmp_path / "shop_43.db")
    seed.build(conn, rng_seed=43)
    facts = _scenario("S12")["facts"]
    event_id = conn.execute("SELECT MIN(id) FROM events").fetchone()[0]
    quote_id = conn.execute("SELECT MIN(id) FROM quotes WHERE status = 'open'").fetchone()[0]
    conn.execute(
        """INSERT INTO proposals (idempotency_key, event_id, kind, quote_id, action, decided_by, confidence,
                                  rationale, facts, exposure_usd, status, final_action, reviewer_note, reviewed_at)
           VALUES (?, ?, 'quote_action', ?, 'contact_customer', 'llm', 0.95, 'r', ?, ?, 'edited', 'absorb',
                   'too small to call about', datetime('now'))""",
        (f"{event_id}:{quote_id}", event_id, quote_id, json.dumps(facts), facts["exposure_usd"]))
    conn.commit()
    conn.close()
    rows = review_shop.export()
    assert len(rows) == 1
    r = rows[0]
    assert (r["shop"], r["outcome"], r["final_action"], r["note"]) == (43, "action_changed", "absorb",
                                                                        "too small to call about")


# --- batch mode -------------------------------------------------------------

class _FakeBatches:
    """Stands in for client.messages.batches: answers every request with the scenario's gold action."""

    def __init__(self, fail_quote=None):
        self.requests, self.fail_quote = None, fail_quote
        self.gold = {s["facts"]["quote_id"]: s["expected"] for s in scenarios()}

    def create(self, requests):
        self.requests = requests
        return SimpleNamespace(id="batch_1")

    def retrieve(self, batch_id):
        return SimpleNamespace(processing_status="ended")

    def results(self, batch_id):
        for rq in self.requests:
            facts = json.loads(rq["params"]["messages"][0]["content"])
            if facts["quote_id"] == self.fail_quote:
                yield SimpleNamespace(custom_id=rq["custom_id"], result=SimpleNamespace(type="errored", error="overloaded"))
                continue
            prices = " ".join(f"${ln['proposed_unit_price']:.4f}" for ln in facts["lines"])
            text = json.dumps({"action": self.gold[facts["quote_id"]], "confidence": 0.9, "rationale": "r",
                               "email_subject": "s", "email_body": f"Hi Jordan, new prices: {prices}"})
            usage = SimpleNamespace(input_tokens=100, output_tokens=50, cache_creation_input_tokens=0,
                                    cache_read_input_tokens=1000)
            msg = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)], usage=usage)
            yield SimpleNamespace(custom_id=rq["custom_id"], result=SimpleNamespace(type="succeeded", message=msg))


def _fake_client(monkeypatch, batches):
    monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(messages=SimpleNamespace(batches=batches)))


def test_batch_runs_only_model_calls_and_fills_the_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "OUT_DIR", tmp_path)
    fake = _FakeBatches()
    _fake_client(monkeypatch, fake)
    cases = [_scenario("S01"), _scenario("S12")]

    assert replay.submit_batch(["C0", "C1a"], cases, k=2) == "batch_1"
    # C0 runs 2K = 4 per case (8); C1a settles S12 by rule locally, so only S01 x 2 goes out
    assert len(fake.requests) == 10
    assert all(rq["params"]["system"][0]["cache_control"] == {"type": "ephemeral"} for rq in fake.requests)
    assert all("fallbacks" not in rq["params"] for rq in fake.requests)

    replay.collect_batch(cases, poll_seconds=0)
    assert not replay.pending_batch_path().exists()
    assert replay.outcomes(BASELINE, cases, k=4) == {"S01": ["reprice"] * 4, "S12": ["contact_customer"] * 4}
    c1a = replay.load_cache("C1a")
    assert c1a["S12:0"]["mode"] == "rule" and c1a["S01:0"]["mode"] == "batch"
    assert replay.submit_batch(["C0", "C1a"], cases, k=2) is None          # everything cached


def test_batch_failures_are_retried_next_run(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "OUT_DIR", tmp_path)
    cases = [_scenario("S01"), _scenario("S04")]
    _fake_client(monkeypatch, _FakeBatches(fail_quote=_scenario("S04")["facts"]["quote_id"]))
    replay.submit_batch(["C2"], cases, k=2)
    replay.collect_batch(cases, poll_seconds=0)
    assert replay.outcomes(CANDIDATES["C2"], cases, k=2) == {"S01": ["reprice"] * 2, "S04": []}

    retry = _FakeBatches()
    _fake_client(monkeypatch, retry)
    replay.submit_batch(["C2"], cases, k=2)
    assert len(retry.requests) == 2                                         # only the failed S04 replays


def test_a_pending_batch_blocks_a_second_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "OUT_DIR", tmp_path)
    _fake_client(monkeypatch, _FakeBatches())
    replay.submit_batch(["C2"], [_scenario("S01")], k=1)
    with pytest.raises(SystemExit):
        replay.submit_batch(["C2"], [_scenario("S01")], k=1)


def test_batch_params_match_the_live_request():
    cand = CANDIDATES["C1b"]
    p = replay.batch_params(cand, _scenario("S01")["facts"])
    assert p["system"][0]["text"] == system_prompt(cand.policy)
    assert p["output_config"]["effort"] == "low"
    assert "absorb" in json.dumps(p["output_config"]["format"]["schema"])
    assert "absorb" not in json.dumps(replay.batch_params(BASELINE, _scenario("S01")["facts"])["output_config"])


def test_replay_cost_prices_batch_and_cache():
    live = {"model": "claude-sonnet-5-5", "input_tokens": 1_000_000, "output_tokens": 0}
    batch = {**live, "batch": True}
    cached = {"model": "claude-sonnet-5-5", "input_tokens": 0, "output_tokens": 0,
              "cache_read_input_tokens": 1_000_000, "batch": True}
    assert replay.replay_cost([live]) == pytest.approx(2.00)
    assert replay.replay_cost([batch]) == pytest.approx(1.00)
    assert replay.replay_cost([cached]) == pytest.approx(0.10)


# --- replays-needed curve ---------------------------------------------------

def test_known_flaky_is_any_case_whose_baseline_disagrees_with_itself():
    from evals.promotion.curve import known_flaky
    pool = {"A": ["reprice"] * 4, "B": ["reprice", "contact_customer", "reprice", "reprice"], "C": []}
    assert known_flaky(pool) == frozenset({"B"})


def test_draws_are_without_replacement_and_capped_at_the_pool():
    import random
    from evals.promotion.curve import _draw
    pool = {"A": ["a", "b", "c"], "B": ["x"]}
    d = _draw(pool, 3, random.Random(0))
    assert sorted(d["A"]) == ["a", "b", "c"] and d["B"] == ["x"]
    assert len(_draw(pool, 2, random.Random(0))["A"]) == 2


def test_should_covers_every_candidate():
    from evals.promotion.curve import BAD, SHOULD
    assert set(SHOULD) == set(CANDIDATES)
    assert all(SHOULD[c] == "reject" for c in BAD)


def test_gate_without_bootstrap_keeps_the_mean():
    cases = _cases(2)
    base = {"X0": _acts(8, 8), "X1": _acts(8, 8)}
    cand = {"X0": _acts(8, 8), "X1": _acts(4, 8)}
    fast = gate(BASELINE, cases, base, cand, bootstrap=False)
    slow = gate(BASELINE, cases, base, cand)
    assert fast.verdict == slow.verdict and fast.diff[0] == pytest.approx(slow.diff[0])


def test_v3_tests_targets_as_their_own_family():
    cases = replay_cases()
    cand = CANDIDATES["C1a"]
    targets = set(cand.targets(cases))
    k = 4                                            # a clean fix at K=4: Fisher p = 0.029
    base = {c["id"]: ([cand.key(c)] * k if c["id"] not in targets else ["contact_customer"] * k) for c in cases}
    fixed = {c["id"]: [cand.key(c)] * k for c in cases}
    assert gate(cand, cases, base, fixed).verdict == "promote"                 # v3: targets corrected among 7
    assert gate(cand, cases, base, fixed, version=2).verdict == "hold"         # v2: corrected among all 62


def test_report_min_k_matches_fisher():
    from evals.promotion.report import _min_k
    assert _min_k(0.05, 1.0) == 4
    assert _min_k(0.05, 62 / 7) == 6


# --- correction ledger ------------------------------------------------------

def _review(exposure=30.0, note=None, proposed="contact_customer", final=None, outcome="approved_as_is",
            customer_id="C-99", tier="standard", value=2_000):
    s = _scenario("S04")["facts"]
    facts = {**s, "exposure_usd": exposure, "contract_note": note, "customer_id": customer_id,
             "customer_tier": tier, "quote_value_usd": value}
    return {"facts": facts, "proposed": proposed, "final_action": final, "outcome": outcome, "note": None}


def test_ledger_status_separates_safe_from_wanted():
    from evals.promotion.ledger import status
    na = {"applies": False, "support": 0, "contradict": 0}
    assert status(None, na)[0] == "proposed"
    assert status({"verdict": "reject", "reasons": ["x"]}, na)[0] == "rejected"
    assert status({"verdict": "hold", "reasons": ["x"]}, na)[0] == "held"
    assert status({"verdict": "promote", "reasons": []}, na)[0] == "promoted"
    safe = {"verdict": "promote", "reasons": []}
    st, why = status(safe, {"applies": True, "support": 1, "contradict": 5})
    assert st == "held" and "not wanted" in why
    assert status(safe, {"applies": True, "support": 3, "contradict": 1})[0] == "promoted"
    assert status(safe, {"applies": True, "support": 1, "contradict": 0})[0] == "held"     # one override isn't enough


def test_ledger_evidence_rules():
    from evals.promotion.ledger import any_note_call_evidence, de_minimis_evidence
    assert de_minimis_evidence(_review(exposure=30, final="absorb", outcome="action_changed")) == "support"
    assert de_minimis_evidence(_review(exposure=30)) == "contradict"
    assert de_minimis_evidence(_review(exposure=80)) is None
    assert de_minimis_evidence(_review(exposure=30, outcome="rejected")) is None
    # a note on a card the policy sends to email: calling supports, emailing contradicts
    assert any_note_call_evidence(_review(note="Net 45", proposed="reprice", final="contact_customer",
                                          outcome="action_changed")) == "support"
    assert any_note_call_evidence(_review(note="Net 45", proposed="reprice")) == "contradict"
    # the policy already calls ($20k): says nothing about the note
    assert any_note_call_evidence(_review(note="Net 45", value=20_000)) is None
    assert any_note_call_evidence(_review(note=None, proposed="reprice")) is None


def test_ledger_appends_versions_only_when_something_moves():
    from evals.promotion.ledger import merge
    entry = {"id": "L-1", "status": "held", "reason": "r", "safe": {"verdict": "promote", "counts": {"fixed": 1}},
             "wanted": {"support": 1, "contradict": 5}}
    led = merge({}, [entry], "2026-10-14")
    assert [v["version"] for v in led["entries"][0]["versions"]] == [1]
    led = merge(led, [entry], "2026-10-15")                       # nothing changed: no new version
    assert len(led["entries"][0]["versions"]) == 1
    moved = {**entry, "status": "promoted", "wanted": {"support": 4, "contradict": 1}}
    led = merge(led, [moved], "2026-10-20")
    vs = led["entries"][0]["versions"]
    assert [(v["version"], v["status"], v["date"]) for v in vs] == [(1, "held", "2026-10-14"), (2, "promoted", "2026-10-20")]


def test_ledger_covers_every_candidate():
    from evals.promotion.ledger import PROPOSALS
    replayed = {p.candidate for p in PROPOSALS if p.candidate}
    assert replayed == set(CANDIDATES) - {"C0"}
