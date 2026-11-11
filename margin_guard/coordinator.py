"""The coordination layer: route each pending event through the agents that act on it.

    price_change.detected      load -> impact -> restate -> decide -> persist
    price_change.needs_review  load -> review ----------------------> persist

restate handles changes that arrive out of date order: pending cards dated after
this change were computed without it, so they are recomputed, re-decided and
replace the stale card. A card a person already approved is never changed; it
gets a linked correction card (original vs revised numbers) instead, and a
person decides whether to re-decide it (quote.redecide: load -> decide -> persist). The result is the same live cards whatever order the
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


MATERIAL_USD = "1.00"   # a correction smaller than this (and not crossing the floor) isn't raised


class EventState(TypedDict, total=False):
    event_id: int
    event_type: str
    payload: dict
    impacts: list[dict]
    restated: list[dict]              # {"proposal_id", "event_id", "facts"} per stale card
    corrections: list[dict]           # the same for cards a person already decided
    proposals: list[dict]
    restated_proposals: list[dict]
    result: dict


def build_graph(conn: sqlite3.Connection, decider: decide.Decider = decide.llm_decide):
    def load(state: EventState) -> EventState:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (state["event_id"],)).fetchone()
        return {"event_type": row["event_type"], "payload": json.loads(row["payload"])}

    def route(state: EventState) -> str:
        if state["event_type"] == "price_change.needs_review":
            return "review"
        if state["event_type"] == "quote.redecide":
            return "redecide"
        return "impact"

    def redecide(state: EventState) -> EventState:
        """A person asked to re-decide an approved card with corrected numbers."""
        return {"impacts": [state["payload"]["facts"]]}

    def review(state: EventState) -> EventState:
        p = state["payload"]
        reasons = p.get("review_reasons", [])
        proposal = {
            "kind": "event_review", "quote_id": None, "action": "resolve_event", "decided_by": "rule",
            "rule_id": "needs_review", "confidence": None, "facts": p, "exposure_usd": 0.0,
            "rationale": ("Invoice needs a person: " if p.get("kind") == "invoice_drift" else "Vendor email needs a person: ")
                         + "; ".join(reasons),
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
                     f"{names.get(costing, costing)}, the supplier it's costed at. Recorded; margins unchanged."
                     if costing else
                     f"{names.get(p.get('vendor_id'), p.get('vendor_id'))} quotes {material} at ${new:.2f}/lb from "
                     f"{p['effective_date']}, but no costing supplier is set for {material}, so no supplier's price "
                     f"moves its margins. Recorded; mark a costing supplier to use it."),
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
            return {"restated": [], "corrections": []}
        return {"restated": restatements(conn, state["event_id"], p),
                "corrections": restatements(conn, state["event_id"], p, decided=True)}

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
        # A decided card is never changed: it gets a linked correction card instead.
        corrections = 0
        for c in state.get("corrections", []):
            corrections += raise_correction(conn, state["event_id"], state["payload"], c)
        result = {
            **state.get("result", {}),
            "affected_quotes": sum(1 for p in proposals if p["kind"] == "quote_action"),
            "restated": len(restated),
            "corrections": corrections,
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
    g.add_node("redecide", redecide)
    g.add_node("decide", decide_node)
    g.add_node("persist", persist)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", route, {"review": "review", "impact": "impact", "redecide": "redecide"})
    g.add_edge("redecide", "decide")
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


def restatements(conn: sqlite3.Connection, event_id: int, change: dict, decided: bool = False) -> list[dict]:
    """Pending cards dated after `change` that it makes stale, recomputed.

    With decided=True: the same for cards a person already approved or edited.
    Those are never touched; the caller raises a correction card for each.

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
           WHERE p.kind = 'quote_action' AND p.event_id <> ?
             AND p.status IN ({statuses})
             AND json_extract(p.facts, '$.effective_date') >= ?
           ORDER BY p.id""".format(statuses="'approved', 'edited'" if decided else "'pending'"),
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


def _summary(facts: dict) -> dict:
    return {"margin_after": facts["margin_after"], "exposure_usd": facts["exposure_usd"],
            "effective_date": facts["effective_date"],
            "cost_changes": [{k: c[k] for k in ("material_id", "cost_after", "effective_date")}
                             for c in facts.get("cost_changes", [])],
            "lines": [{k: ln[k] for k in ("line_id", "part_name", "qty", "unit_price", "unit_cost_after",
                                          "proposed_unit_price")} for ln in facts["lines"]]}


def raise_correction(conn: sqlite3.Connection, event_id: int, change: dict, c: dict) -> int:
    """A card a person approved was computed without a change that arrived later.

    The approved decision stands (prices it wrote, emails it queued). A linked
    correction card puts the original and the revised numbers side by side, and a
    person decides: keep the decision, or re-decide with the revised numbers (a
    separate event). Only the newest correction per approved card stays open.
    Returns 1 if a card was raised.
    """
    orig = conn.execute("SELECT * FROM proposals WHERE id = ?", (c["proposal_id"],)).fetchone()
    old = json.loads(orig["facts"])
    revised = c["facts"]
    # Only a material correction interrupts a person: dollars at risk move by $1 or
    # more, or the margin crosses the floor (either way).
    floor = old["margin_floor"]
    crossed = (old["margin_after"] < floor) != (revised["margin_after"] < floor)
    if abs(money.D(revised["exposure_usd"]) - money.D(old["exposure_usd"])) < money.D(MATERIAL_USD) and not crossed:
        return 0
    material = conn.execute("SELECT name FROM materials WHERE id = ?", (change["material_id"],)).fetchone()["name"]
    reason = (f"The {material} change effective {change['effective_date']} arrived after {orig['quote_id']} was "
              f"decided ({orig['final_action']}), and its cost was missing from that decision.")
    facts = {
        "kind": "correction",
        "email_id": change.get("email_id"),
        "vendor_id": change.get("vendor_id"),
        "quote_id": orig["quote_id"],
        "customer_name": old["customer_name"],
        "corrects": orig["id"],
        "original": {"action": orig["action"], "final_action": orig["final_action"],
                     "status": orig["status"], "reviewed_at": orig["reviewed_at"], **_summary(old)},
        "revised": revised,
        "margin_floor": old["margin_floor"],
        "review_reasons": [
            reason,
            f"Margin after: {old['margin_after']:.1%} as decided, {revised['margin_after']:.1%} with the change "
            f"(floor {old['margin_floor']:.1%}); at risk ${old['exposure_usd']:,.2f} -> ${revised['exposure_usd']:,.2f}.",
        ],
    }
    proposal = {
        "kind": "event_review", "quote_id": orig["quote_id"], "action": "resolve_event", "decided_by": "rule",
        "rule_id": "correction", "confidence": None, "facts": facts, "exposure_usd": 0.0,
        "rationale": "An approved decision needs another look: " + reason,
        "draft_subject": None, "draft_body": None,
    }
    cur = conn.execute(
        """INSERT OR IGNORE INTO proposals
           (idempotency_key, event_id, quote_id, kind, action, decided_by, rule_id, confidence,
            rationale, draft_subject, draft_body, facts, exposure_usd)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (f"correction:{orig['id']}:{event_id}", event_id, orig["quote_id"], proposal["kind"], proposal["action"],
         proposal["decided_by"], proposal["rule_id"], None, proposal["rationale"], None, None,
         json.dumps(facts), 0.0),
    )
    if not cur.rowcount:
        return 0
    new_id = cur.lastrowid
    # An older open correction for the same approved card is covered by this one.
    for r in conn.execute(
            """SELECT id FROM proposals WHERE kind = 'event_review' AND status = 'pending' AND id <> ?
               AND json_extract(facts, '$.kind') = 'correction' AND json_extract(facts, '$.corrects') = ?""",
            (new_id, orig["id"])).fetchall():
        conn.execute("UPDATE proposals SET status = 'superseded', superseded_by = ?, supersede_reason = ? WHERE id = ?",
                     (new_id, "a newer correction includes this one", r["id"]))
    return 1


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
            f" don't include this change; a correction card asks a person to check that decision.")


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
