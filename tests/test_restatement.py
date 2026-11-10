"""Out-of-order supplier changes: the live cards must not depend on arrival order.

A card dated D is priced on every change effective on or before D. When an
earlier-dated change arrives after that card was made, the card is restated:
recomputed with the change, re-decided, and it replaces the stale one.
"""

import json

import pytest
from test_coordinator import POLICY_DECIDER
from test_pipeline import PERFECT_EXTRACTIONS, _ch, _ex

from margin_guard import actions, coordinator, events, ingest
from margin_guard.decide import decision_key
from margin_guard.parser import normalize

GLE = {"id": "T-GLE", "from_addr": "sales@glelastomers.com"}
RCB = {"id": "T-RCB", "from_addr": "customerservice@ridgelinecarbon.com"}
KRD = {"id": "T-KRD", "from_addr": "sales@keystonerubber.com"}

NBR_NOV15 = (GLE, _ex("price_change", [_ch("NBR 70", 2.36, "lb", "2026-11-15")]))
N550_NOV1 = (RCB, _ex("price_change", [_ch("N550", 1.18, "lb", "2026-11-01")]))


def _deliver(conn, email, extraction):
    [draft] = normalize(conn, email, extraction).drafts
    event_id = events.append(conn, draft, source_ref=f"email:{email['id']}")
    coordinator.run(conn, POLICY_DECIDER)
    return event_id


def _cards(conn, quote_id):
    return [dict(r) | {"facts": json.loads(r["facts"])} for r in conn.execute(
        "SELECT * FROM proposals WHERE quote_id = ? AND kind = 'quote_action' ORDER BY id", (quote_id,))]


def _live(conn):
    """Each quote's live cards, by what a person sees (not which change triggered them)."""
    out: dict[str, list] = {}
    for p in conn.execute("SELECT quote_id, action, exposure_usd, facts FROM proposals"
                          " WHERE kind = 'quote_action' AND status = 'pending'"):
        f = json.loads(p["facts"])
        out.setdefault(p["quote_id"], []).append(
            (f["effective_date"], p["action"], p["exposure_usd"], f["margin_after"],
             tuple(sorted((c["material_id"], c["cost_after"]) for c in f["cost_changes"]))))
    return {q: sorted(v) for q, v in out.items()}


@pytest.fixture
def both_materials_quote(conn):
    """An open quote with a part using NBR 70 and N550 (P-1007), still open on Nov 15."""
    row = conn.execute(
        """SELECT DISTINCT q.id FROM quotes q JOIN quote_lines ql ON ql.quote_id = q.id
           WHERE q.status = 'open' AND ql.part_id = 'P-1007' AND q.valid_until >= '2026-11-15'
           ORDER BY q.id LIMIT 1""").fetchone()
    assert row, "seed needs an open P-1007 quote valid through Nov 15"
    return row[0]


def test_earlier_change_arriving_later_restates_the_card(conn, both_materials_quote):
    q = both_materials_quote
    _deliver(conn, *NBR_NOV15)
    [nov15] = _cards(conn, q)
    assert [c["material_id"] for c in nov15["facts"]["cost_changes"]] == ["MAT-NBR-70"]

    _deliver(conn, *N550_NOV1)
    cards = {c["id"]: c for c in _cards(conn, q)}
    live = [c for c in cards.values() if c["status"] == "pending"]
    [restated] = live
    # The live card is the Nov 15 card, redone with the Nov 1 carbon black increase.
    assert restated["facts"]["effective_date"] == "2026-11-15"
    assert {c["material_id"] for c in restated["facts"]["cost_changes"]} == {"MAT-NBR-70", "MAT-CB-N550"}
    assert restated["facts"]["restated"]["replaces_card"] == nov15["id"]
    assert restated["event_id"] == nov15["event_id"]
    assert restated["exposure_usd"] > nov15["exposure_usd"]
    # The stale card says why it was replaced.
    old = cards[nov15["id"]]
    assert old["status"] == "superseded" and old["superseded_by"] == restated["id"]
    assert "Carbon black N550" in old["supersede_reason"] and "2026-11-01" in old["supersede_reason"]
    # The new Nov 1 card is covered by the restated Nov 15 card.
    nov1 = next(c for c in cards.values() if c["facts"]["effective_date"] == "2026-11-01")
    assert nov1["status"] == "superseded" and nov1["superseded_by"] == restated["id"]


def test_either_arrival_order_gives_the_same_live_card(conn, tmp_path, both_materials_quote):
    from margin_guard import db, seed
    other = db.connect(tmp_path / "other.db")
    seed.build(other)
    _deliver(conn, *NBR_NOV15)
    _deliver(conn, *N550_NOV1)
    _deliver(other, *N550_NOV1)
    _deliver(other, *NBR_NOV15)
    assert _live(conn) == _live(other)
    other.close()


def test_shop_inbox_live_cards_do_not_depend_on_arrival_order(conn, tmp_path):
    """The seeded inbox arrives out of date order (E02's Nov 15 before E09's Nov 1).
    Processing it in arrival order and in reverse date order must agree."""
    from margin_guard import db, seed

    def process(c, key):
        ingest.run(c, extract=lambda e: PERFECT_EXTRACTIONS[e["id"]])
        pending = c.execute("SELECT id, payload FROM events WHERE status = 'pending'").fetchall()
        c.execute("UPDATE events SET status = 'processed' WHERE status = 'pending'")
        for ev in sorted(pending, key=key):
            c.execute("UPDATE events SET status = 'pending' WHERE id = ?", (ev["id"],))
            coordinator.run(c, POLICY_DECIDER)

    other = db.connect(tmp_path / "reverse.db")
    seed.build(other)
    process(conn, key=lambda ev: ev["id"])
    process(other, key=lambda ev: (-int((json.loads(ev["payload"]).get("effective_date") or "0").replace("-", "")),
                                   ev["id"]))
    assert _live(conn) == _live(other)
    restated = conn.execute("SELECT COUNT(*) FROM proposals WHERE json_extract(facts, '$.restated') IS NOT NULL")
    assert restated.fetchone()[0] > 0, "the seeded inbox should exercise restatement"
    other.close()


def test_no_restatement_when_the_numbers_do_not_move(conn, both_materials_quote):
    _deliver(conn, *NBR_NOV15)
    # Same N550 cost as today, dated Nov 1: nothing on the card changes.
    _deliver(conn, RCB, _ex("price_change", [_ch("N550", 1.09, "lb", "2026-11-01")]))
    assert not [c for c in _cards(conn, both_materials_quote) if c["facts"].get("restated")]


def test_alternate_supplier_change_restates_nothing(conn, both_materials_quote):
    _deliver(conn, *NBR_NOV15)
    before = _live(conn)
    _deliver(conn, KRD, _ex("price_change", [_ch("NBR 70", 2.50, "lb", "2026-11-01")]))
    assert _live(conn) == before


def test_decided_cards_are_left_alone_and_flagged(conn, both_materials_quote):
    q = both_materials_quote
    _deliver(conn, *NBR_NOV15)
    [nov15] = _cards(conn, q)
    actions.review(conn, nov15["id"], "approve")
    _deliver(conn, *N550_NOV1)
    cards = {c["id"]: c for c in _cards(conn, q)}
    assert cards[nov15["id"]]["status"] == "approved"
    assert not [c for c in cards.values() if c["facts"].get("restated")]
    [nov1] = [c for c in cards.values() if c["id"] != nov15["id"]]
    assert f"#{nov15['id']}" in nov1["rationale"] and "check that decision" in nov1["rationale"]


def test_restated_decisions_get_their_own_cache_key():
    facts = {"quote_id": "Q-1", "material_id": "MAT-NBR-70", "effective_date": "2026-11-15",
             "cost_changes": [{"material_id": "MAT-NBR-70", "cost_after": 2.36}]}
    assert decision_key(facts) == "Q-1:MAT-NBR-70:2026-11-15"     # unchanged for ordinary cards
    restated = facts | {"restated": {"replaces_card": 1, "reason": "r"},
                        "cost_changes": facts["cost_changes"] + [{"material_id": "MAT-CB-N550", "cost_after": 1.18}]}
    assert decision_key(restated).startswith("Q-1:MAT-NBR-70:2026-11-15:r")
