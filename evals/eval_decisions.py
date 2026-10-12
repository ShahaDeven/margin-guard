"""Score the coordinator's quote decisions against the reference policy.

    python -m evals.eval_decisions            # calls Claude for the below-floor quotes
    python -m evals.eval_decisions --replay   # rescore cached decisions, no API calls

Extraction is replayed from evals/results/extractions.json (run
evals.eval_extraction once first), so this eval measures decisions only.
"""

import argparse
import json
import re
import tempfile
from collections import Counter
from pathlib import Path

from evals.reference_policy import expected_action
from margin_guard import coordinator, db, ingest, seed
from margin_guard.config import MODEL
from margin_guard.decide import QuoteDecision
from margin_guard.parser import EmailExtraction

RESULTS_DIR = Path(__file__).resolve().parent / "results"
EXTRACTIONS = RESULTS_DIR / "extractions.json"
DECISIONS_CACHE = RESULTS_DIR / "decisions.json"
_NUMBER = re.compile(r"\d[\d,]*\.\d+|\d[\d,]*")


def decision_key(facts: dict) -> str:
    return f"{facts['quote_id']}:{facts['material_id']}:{facts['effective_date']}"


def draft_uses_proposed_prices(facts: dict, body: str | None) -> bool:
    """Every repriced line's proposed price appears in the draft (to the cent)."""
    if not body:
        return False
    numbers = [float(n.replace(",", "")) for n in _NUMBER.findall(body)]
    changed = [ln["proposed_unit_price"] for ln in facts["lines"] if ln["proposed_unit_price"] != ln["unit_price"]]
    return all(any(abs(n - p) <= 0.005 for n in numbers) for p in changed)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", action="store_true", help="reuse cached decisions instead of calling Claude")
    args = ap.parse_args()

    if not EXTRACTIONS.exists():
        raise SystemExit("Run `python -m evals.eval_extraction` first to cache extractions.")
    extractions = json.loads(EXTRACTIONS.read_text(encoding="utf-8"))

    cache: dict = json.loads(DECISIONS_CACHE.read_text(encoding="utf-8")) if args.replay else {}
    if args.replay:
        decider = lambda facts: QuoteDecision.model_validate(cache[decision_key(facts)])  # noqa: E731
    else:
        from margin_guard.decide import llm_decide

        def decider(facts):
            d = llm_decide(facts)
            cache[decision_key(facts)] = d.model_dump()
            return d

    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "eval.db")
        seed.build(conn)
        ingest.run(conn, extract=lambda e: EmailExtraction.model_validate(extractions[e["id"]]))
        print(f"\nCoordinating ({'replay' if args.replay else MODEL})")
        coordinator.run(conn, decider)
        if not args.replay:
            DECISIONS_CACHE.write_text(json.dumps(cache, indent=2), encoding="utf-8")

        rows = conn.execute(
            """SELECT p.*, e.payload AS event_payload FROM proposals p JOIN events e ON e.id = p.event_id
               ORDER BY p.event_id, p.quote_id"""
        ).fetchall()
        event_rows = conn.execute(
            "SELECT id, event_type, payload, result FROM events WHERE source_ref LIKE 'email:%' ORDER BY id"
        ).fetchall()
        conn.close()

    scored = []
    for r in rows:
        if r["kind"] != "quote_action":
            continue
        facts = json.loads(r["facts"])
        expected = expected_action(facts)
        scored.append({
            "quote_id": r["quote_id"], "material_id": facts["material_id"], "customer": facts["customer_name"],
            "tier": facts["customer_tier"], "value": facts["quote_value_usd"],
            "margin": f"{facts['margin_before']:.1%} -> {facts['margin_after']:.1%} (floor {facts['margin_floor']:.1%})",
            "decided_by": r["decided_by"], "rule_id": r["rule_id"], "action": r["action"],
            "expected": expected, "correct": r["action"] == expected, "confidence": r["confidence"],
            "draft_ok": draft_uses_proposed_prices(facts, r["draft_body"]) if r["decided_by"] == "llm" else None,
            "exposure_usd": r["exposure_usd"], "status": r["status"],
        })

    def acc(items):
        return sum(i["correct"] for i in items) / len(items) if items else None

    rule_items = [s for s in scored if s["decided_by"] == "rule"]
    llm_items = [s for s in scored if s["decided_by"] == "llm"]
    summary = {
        "model": "replay" if args.replay else MODEL,
        "quote_decisions": len(scored),
        "overall_accuracy": acc(scored),
        "rule_decisions": len(rule_items), "rule_accuracy": acc(rule_items),
        "llm_decisions": len(llm_items), "llm_accuracy": acc(llm_items),
        "escalated": sum(1 for s in scored if s["decided_by"] == "error"),
        "draft_price_fidelity": (sum(s["draft_ok"] for s in llm_items) / len(llm_items)) if llm_items else None,
        "actions": dict(Counter(s["action"] for s in scored)),
        "superseded": sum(1 for s in scored if s["status"] == "superseded"),
        "live_cards": sum(1 for s in scored if s["status"] == "pending"),
        # Exposure on live cards only; a superseded card's loss is inside its replacement's.
        "total_exposure_usd": round(sum(s["exposure_usd"] for s in scored if s["status"] == "pending"), 2),
        "review_items": sum(1 for r in rows if r["kind"] == "event_review"),
    }

    fmt = lambda v: "-" if v is None else f"{v:.0%}"  # noqa: E731
    lines = ["### Events", "", "| Event | Material | Affected quotes | Actions | Exposure |", "|---|---|---|---|---|"]
    for ev in event_rows:
        p, res = json.loads(ev["payload"]), json.loads(ev["result"] or "{}")
        if ev["event_type"] == "price_change.needs_review":
            lines.append(f"| {p['email_id']} | (needs review) | - | - | - |")
            continue
        acts = ", ".join(f"{k} {v}" for k, v in res.get("actions", {}).items()) or res.get("note", "-")
        lines.append(f"| {p['email_id']} | {p['material_id']} {p['pct_change']:+.1%} | {res.get('affected_quotes', 0)} "
                     f"| {acts} | ${res.get('exposure_usd', 0):,.2f} |")

    lines += ["", "### Judgment calls (Claude)", "",
              "| Quote | Customer | Tier | Value | Margin | Expected | Got | Conf. | Draft prices |",
              "|---|---|---|---|---|---|---|---|---|"]
    for s in llm_items:
        mark = "PASS" if s["correct"] else "FAIL"
        quote = s["quote_id"] + (" (superseded)" if s["status"] == "superseded" else "")
        lines.append(f"| {quote} | {s['customer']} | {s['tier']} | ${s['value']:,.0f} | {s['margin']} "
                     f"| {s['expected']} | {mark} {s['action']} | {s['confidence']:.2f} | {'ok' if s['draft_ok'] else 'MISSING'} |")

    lines += [
        "",
        f"- Quote decisions: **{len(scored)}** (rules {len(rule_items)}, Claude {len(llm_items)}, "
        f"escalated {summary['escalated']}); review items: {summary['review_items']}",
        f"- Accuracy vs policy: overall **{fmt(summary['overall_accuracy'])}**, rules **{fmt(summary['rule_accuracy'])}**, "
        f"Claude **{fmt(summary['llm_accuracy'])}**",
        f"- Drafts quoting the proposed prices correctly: **{fmt(summary['draft_price_fidelity'])}**",
        f"- Superseded by a newer card for the same quote: **{summary['superseded']}**; "
        f"live cards for a person: **{summary['live_cards']}**",
        f"- Actions: {summary['actions']}; exposure on live cards **${summary['total_exposure_usd']:,.2f}**",
    ]
    report = "\n".join(lines)
    print("\n" + report)
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "decision_report.md").write_text(report + "\n", encoding="utf-8")
    (RESULTS_DIR / "decision_results.json").write_text(
        json.dumps({"summary": summary, "decisions": scored}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
