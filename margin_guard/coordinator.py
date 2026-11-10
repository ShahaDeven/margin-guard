"""The coordination layer: route each pending event through the agents that act on it.

    price_change.detected      load -> impact -> restate -> decide -> persist
    price_change.needs_review  load -> review ----------------------> persist

restate handles changes that arrive out of date order: pending cards dated after
this change were computed without it, so they are recomputed, re-decided and
replace the stale card. The result is the same live cards whatever order the
supplier emails arrive in.

Routing is deterministic code; the LLM is only used inside `decide` for judgment
calls. impact and decide only read; every write (the price history row, the
proposals, superseding, marking the event processed) happens in `persist` as one
short transaction. The database is never write-locked while Claude is thinking,
and an event is acted on exactly once.

    python -m margin_guard.coordinator
"""

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from . import catalog, db, decide, events, impact, money
from .config import AS_OF, DB_PATH


class EventState(TypedDict, total=False):
    event_id: int
    event_type: str
    payload: dict
    impacts: list[dict]
    restated: list[dict]              # {"proposal_id", "event_id", "facts"} per stale card
    proposals: list[dict]
    restated_proposals: list[dict]
    result: dict


def build_graph(conn: sqlite3.Connection, decider: decide.Decider = decide.llm_decide):
    def load(state: EventState) -> EventState:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (state["event_id"],)).fetchone()
        return {"event_type": row["event_type"], "payload": json.loads(row["payload"])}

    def route(state: EventState) -> str:
        return "review" if state["event_type"] == "price_change.needs_review" else "impact"

    def review(state: EventState) -> EventState:
        p = state["payload"]
        reasons = p.get("review_reasons", [])
        proposal = {
            "kind": "event_review", "quote_id": None, "action": "resolve_event", "decided_by": "rule",
            "rule_id": "needs_review", "confidence": None, "facts": p, "exposure_usd": 0.0,
            "rationale": "Vendor email needs a person: " + "; ".join(reasons),
            "draft_subject": None, "draft_body": None,
        }
        return {"proposals": [proposal], "result": {"review_reasons": reasons}}

    def record_change(event_id: int, p: dict) -> None:
        conn.execute(
            "INSERT INTO material_price_history (material_id, vendor_id, cost_per_lb, effective_date, source_event_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (p["material_id"], p["vendor_id"], p["new_cost_per_lb"], p["effective_date"], event_id),
        )
        # The catalog cost is the costing supplier's price today; an alternate
        # supplier's price is history only.
        if p["effective_date"] <= AS_OF.isoformat() and impact.moves_costing(conn, p):
            conn.execute("UPDATE materials SET cost_per_lb = ? WHERE id = ?", (p["new_cost_per_lb"], p["material_id"]))

    def alt_supplier_result(p: dict) -> dict:
        """A price from a supplier we don't cost this material at: on file, no cards."""
        costing = catalog.costing_vendor(conn, p["material_id"])
        names = dict(conn.execute("SELECT id, name FROM vendors").fetchall())
        material = conn.execute("SELECT name FROM materials WHERE id = ?", (p["material_id"],)).fetchone()["name"]
        ours = impact.cost_on(conn, p["material_id"], p["effective_date"])
        new = p["new_cost_per_lb"]
        return {
            "alt_supplier": True,
            "vendor_id": p.get("vendor_id"),
            "costing_vendor_id": costing,
            "costing_cost_per_lb": ours,
            "note": (f"Alternate supplier: {names.get(p.get('vendor_id'), p.get('vendor_id'))} quotes {material} at "
                     f"${new:.2f}/lb from {p['effective_date']}, vs ${ours:.2f}/lb from "
                     f"{names.get(costing, costing)}, the supplier it's costed at. Recorded; margins unchanged."),
        }

    def impact_node(state: EventState) -> EventState:
        p = state["payload"]
        if not impact.moves_costing(conn, p):
            return {"impacts": [], "result": alt_supplier_result(p)}
        if p.get("pct_change") is not None and p["pct_change"] <= 0:
            return {"impacts": [], "result": {"note": "cost decrease or no change; margins improve, no action"}}
        return {"impacts": impact.affected_quotes(conn, p)}

    def restate_node(state: EventState) -> EventState:
        """Redo pending later-dated cards this change makes stale (see restatements)."""
        p = state["payload"]
        if state["event_type"] != "price_change.detected" or p.get("new_cost_per_lb") is None:
            return {"restated": []}
        return {"restated": restatements(conn, state["event_id"], p)}

    def decide_node(state: EventState) -> EventState:
        restated = [{**decide.decide(r["facts"], decider), "restates": r["proposal_id"], "event_id": r["event_id"]}
                    for r in state.get("restated", [])]
        return {"proposals": [decide.decide(f, decider) for f in state.get("impacts", [])],
                "restated_proposals": restated}

    def insert(event_id: int, key: str, pr: dict) -> int | None:
        cur = conn.execute(
            """INSERT OR IGNORE INTO proposals
               (idempotency_key, event_id, quote_id, kind, action, decided_by, rule_id, confidence,
                rationale, draft_subject, draft_body, facts, exposure_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, event_id, pr["quote_id"], pr["kind"], pr["action"], pr["decided_by"],
             pr["rule_id"], pr["confidence"], pr["rationale"], pr["draft_subject"], pr["draft_body"],
             json.dumps(pr["facts"]), pr["exposure_usd"]),
        )
        return cur.lastrowid if cur.rowcount else None

    def persist(state: EventState) -> EventState:
        if state["event_type"] == "price_change.detected":
            record_change(state["event_id"], state["payload"])
        proposals = state.get("proposals", [])
        superseded = 0
        for pr in proposals:
            if pr["kind"] == "quote_action":
                pr = {**pr, "rationale": pr["rationale"] + decided_later_note(conn, pr["facts"])}
            new_id = insert(state["event_id"], f"{state['event_id']}:{pr['quote_id'] or 'event'}", pr)
            if new_id and pr["kind"] == "quote_action":
                superseded += supersede_older(conn, new_id, pr["facts"])
        # Restated cards replace the stale card they redo, then cover older-dated
        # cards as usual (including the one this change just created).
        restated = state.get("restated_proposals", [])
        for pr in restated:
            still = conn.execute("SELECT status FROM proposals WHERE id = ?", (pr["restates"],)).fetchone()
            if still["status"] != "pending":
                continue
            new_id = insert(pr["event_id"], f"{pr['event_id']}:{pr['quote_id']}:r{state['event_id']}", pr)
            if not new_id:
                continue
            conn.execute("UPDATE proposals SET status = 'superseded', superseded_by = ?, supersede_reason = ?"
                         " WHERE id = ? AND status = 'pending'",
                         (new_id, pr["facts"]["restated"]["reason"], pr["restates"]))
            superseded += 1 + supersede_older(conn, new_id, pr["facts"])
        result = {
            **state.get("result", {}),
            "affected_quotes": sum(1 for p in proposals if p["kind"] == "quote_action"),
            "restated": len(restated),
            "superseded": superseded,
            "exposure_usd": money.out(money.cents(sum((money.D(p["exposure_usd"]) for p in proposals), money.ZERO))),
            "actions": {a: sum(1 for p in proposals if p["action"] == a)
                        for a in sorted({p["action"] for p in proposals})},
        }
        conn.execute("UPDATE events SET status = 'processed', result = ? WHERE id = ?",
                     (json.dumps(result), state["event_id"]))
        return {"result": result}

    g = StateGraph(EventState)
    g.add_node("load", load)
    g.add_node("review", review)
    g.add_node("impact", impact_node)
    g.add_node("restate", restate_node)
    g.add_node("decide", decide_node)
    g.add_node("persist", persist)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", route, {"review": "review", "impact": "impact"})
    g.add_edge("impact", "restate")
    g.add_edge("restate", "decide")
    g.add_edge("decide", "persist")
    g.add_edge("review", "persist")
    g.add_edge("persist", END)
    return g.compile()


def supersede_older(conn: sqlite3.Connection, new_id: int, facts: dict) -> int:
    """Retire older pending cards for the same quote that the new card already covers.

    Costs stack, so a card computed at effective date D includes every change
    effective on or before D. It covers an older card only if (a) the quote can
    still be accepted at D, so the new card reflects the stacked cost rather
    than "honor, expires first", and (b) the older change takes effect no later
    than D. Otherwise both cards stay, because each covers something the other doesn't.
    """
    if not facts["can_accept_after_change"]:
        return 0
    rows = conn.execute(
        "SELECT id, facts FROM proposals WHERE quote_id = ? AND kind = 'quote_action'"
        " AND status = 'pending' AND id <> ?",
        (facts["quote_id"], new_id),
    ).fetchall()
    covered = [r["id"] for r in rows if json.loads(r["facts"])["effective_date"] <= facts["effective_date"]]
    reason = f"covered by a card dated {facts['effective_date']} that includes this change"
    for old_id in covered:
        conn.execute("UPDATE proposals SET status = 'superseded', superseded_by = ?, supersede_reason = ? WHERE id = ?",
                     (new_id, reason, old_id))
    return len(covered)


def _numbers(facts: dict) -> tuple:
    """What a card shows a person; if none of it moves, the card isn't stale."""
    return (facts["exposure_usd"], facts["margin_after"],
            tuple((ln["line_id"], ln["unit_cost_after"], ln["proposed_unit_price"]) for ln in facts["lines"]),
            tuple(sorted((c["material_id"], c["cost_after"]) for c in facts["cost_changes"])))


def restatements(conn: sqlite3.Connection, event_id: int, change: dict) -> list[dict]:
    """Pending cards dated after `change` that it makes stale, recomputed.

    Costs stack by effective date, so a card dated D includes every change on or
    before D that was known when it was made. A change dated on or before D that
    arrives later (supplier emails don't come in date order) is missing from it.
    Each such card is recomputed with the change included; if its numbers move,
    it is returned with its new facts, to be re-decided and to replace the old
    card. Decided cards are left alone: a person has acted on them, and the new
    change's own card says so (decided_later_note).
    """
    if not impact.moves_costing(conn, change):
        return []
    quotes = set(impact.affected_quote_ids(conn, change["material_id"]))
    rows = conn.execute(
        """SELECT p.id, p.event_id, p.quote_id, p.facts, e.payload FROM proposals p
           JOIN events e ON e.id = p.event_id
           WHERE p.kind = 'quote_action' AND p.status = 'pending' AND p.event_id <> ?
             AND json_extract(p.facts, '$.effective_date') >= ?
           ORDER BY p.id""",
        (event_id, change["effective_date"]),
    ).fetchall()
    # A same-date card is normally retired by this change's own card, which
    # includes everything up to that date (supersede_older). Only when the quote
    # expires first is it kept, so then it needs restating too.
    rows = [r for r in rows if json.loads(r["facts"])["effective_date"] > change["effective_date"]
            or not json.loads(r["facts"])["can_accept_after_change"]]
    material = conn.execute("SELECT name FROM materials WHERE id = ?", (change["material_id"],)).fetchone()["name"]
    out = []
    for r in rows:
        if r["quote_id"] not in quotes:
            continue
        old = json.loads(r["facts"])
        new = impact.quote_facts(conn, r["quote_id"], json.loads(r["payload"]), also=(change,))
        if _numbers(new) == _numbers(old):
            continue
        reason = (f"restated: the {material} change effective {change['effective_date']} arrived after this "
                  f"card was made, and its cost was missing from it")
        new["restated"] = {"replaces_card": r["id"], "reason": reason}
        out.append({"proposal_id": r["id"], "event_id": r["event_id"], "facts": new})
    return out


def decided_later_note(conn: sqlite3.Connection, facts: dict) -> str:
    """For a new card: was this quote already decided on a later-dated card that
    couldn't have included this change? Then that decision needs a second look."""
    rows = conn.execute(
        """SELECT id, final_action, facts FROM proposals
           WHERE quote_id = ? AND kind = 'quote_action' AND status IN ('approved', 'edited')""",
        (facts["quote_id"],),
    ).fetchall()
    later = [r for r in rows if json.loads(r["facts"])["effective_date"] > facts["effective_date"]]
    if not later:
        return ""
    cards = ", ".join(f"#{r['id']} ({r['final_action']})" for r in later)
    return (f" Note: this quote was already decided on a later-dated card ({cards}) whose numbers"
            f" don't include this change; check that decision.")


Notify = Callable[[str, dict], None]


def run(conn: sqlite3.Connection, decider: decide.Decider = decide.llm_decide,
        notify: Notify | None = None) -> dict[int, dict]:
    """Process every pending event, oldest first. Returns {event_id: result}.

    `notify(kind, data)` receives progress for a live UI: event.started,
    decision.started (a judgment call going to Claude) and event.processed.
    """
    notify = notify or (lambda kind, data: None)

    def announced(facts: dict) -> decide.QuoteDecision:
        notify("decision.started", {"quote_id": facts["quote_id"], "customer": facts["customer_name"]})
        return decider(facts)

    graph = build_graph(conn, announced)
    results = {}
    for ev in events.pending(conn):
        payload = json.loads(ev["payload"])
        label = str(payload.get("material_id") or payload.get("email_id"))
        notify("event.started", {"event_id": ev["id"], "event_type": ev["event_type"], "label": label})
        try:
            state = graph.invoke({"event_id": ev["id"]})
            conn.commit()
            results[ev["id"]] = state["result"]
        except Exception as exc:
            conn.rollback()
            results[ev["id"]] = {"error": f"{type(exc).__name__}: {exc}"}
            conn.execute("UPDATE events SET status = 'failed', result = ? WHERE id = ?",
                         (json.dumps(results[ev["id"]]), ev["id"]))
            conn.commit()
        notify("event.processed", {"event_id": ev["id"], "label": label, "result": results[ev["id"]]})
        print(f"  event {ev['id']:>3}  {ev['event_type']:<26} {label:<14} {json.dumps(results[ev['id']])}")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--replay", type=Path, metavar="DECISIONS_JSON",
                    help="reuse cached Claude decisions (e.g. evals/results/decisions.json); "
                         "quotes not in the cache still go to Claude")
    args = ap.parse_args()
    conn = db.connect(args.db)

    decider = decide.llm_decide
    if args.replay:
        cache = json.loads(args.replay.read_text(encoding="utf-8"))

        def decider(facts: dict) -> decide.QuoteDecision:
            key = decide.decision_key(facts)
            if key in cache:
                return decide.QuoteDecision.model_validate(cache[key])
            return decide.llm_decide(facts)

    run(conn, decider)
    print()
    for row in conn.execute(
        "SELECT action, decided_by, COUNT(*) n, ROUND(SUM(exposure_usd), 2) usd FROM proposals"
        " WHERE status = 'pending' GROUP BY action, decided_by ORDER BY action"
    ):
        print(f"  {row['action']:<17} by {row['decided_by']:<5} {row['n']:>3} proposals  exposure ${row['usd']:,.2f}")


if __name__ == "__main__":
    main()
