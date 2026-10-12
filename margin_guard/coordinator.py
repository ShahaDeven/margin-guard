"""The coordination layer: route each pending event through the agents that act on it.

    price_change.detected      load -> impact -> decide -> persist
    price_change.needs_review  load -> review -----------> persist

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

from . import db, decide, events, impact
from .config import AS_OF, DB_PATH


class EventState(TypedDict, total=False):
    event_id: int
    event_type: str
    payload: dict
    impacts: list[dict]
    proposals: list[dict]
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
        if p["effective_date"] <= AS_OF.isoformat():
            conn.execute("UPDATE materials SET cost_per_lb = ? WHERE id = ?", (p["new_cost_per_lb"], p["material_id"]))

    def impact_node(state: EventState) -> EventState:
        p = state["payload"]
        if p.get("pct_change") is not None and p["pct_change"] <= 0:
            return {"impacts": [], "result": {"note": "cost decrease or no change; margins improve, no action"}}
        return {"impacts": impact.affected_quotes(conn, p)}

    def decide_node(state: EventState) -> EventState:
        return {"proposals": [decide.decide(f, decider) for f in state.get("impacts", [])]}

    def persist(state: EventState) -> EventState:
        if state["event_type"] == "price_change.detected":
            record_change(state["event_id"], state["payload"])
        proposals = state.get("proposals", [])
        superseded = 0
        for pr in proposals:
            key = f"{state['event_id']}:{pr['quote_id'] or 'event'}"
            cur = conn.execute(
                """INSERT OR IGNORE INTO proposals
                   (idempotency_key, event_id, quote_id, kind, action, decided_by, rule_id, confidence,
                    rationale, draft_subject, draft_body, facts, exposure_usd)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (key, state["event_id"], pr["quote_id"], pr["kind"], pr["action"], pr["decided_by"],
                 pr["rule_id"], pr["confidence"], pr["rationale"], pr["draft_subject"], pr["draft_body"],
                 json.dumps(pr["facts"]), pr["exposure_usd"]),
            )
            if cur.rowcount and pr["kind"] == "quote_action":
                superseded += supersede_older(conn, cur.lastrowid, pr["facts"])
        result = {
            **state.get("result", {}),
            "affected_quotes": sum(1 for p in proposals if p["kind"] == "quote_action"),
            "superseded": superseded,
            "exposure_usd": round(sum(p["exposure_usd"] for p in proposals), 2),
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
    g.add_node("decide", decide_node)
    g.add_node("persist", persist)
    g.add_edge(START, "load")
    g.add_conditional_edges("load", route, {"review": "review", "impact": "impact"})
    g.add_edge("impact", "decide")
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
    for old_id in covered:
        conn.execute("UPDATE proposals SET status = 'superseded', superseded_by = ? WHERE id = ?", (new_id, old_id))
    return len(covered)


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
            key = f"{facts['quote_id']}:{facts['material_id']}:{facts['effective_date']}"
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
