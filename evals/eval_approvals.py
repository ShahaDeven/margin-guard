"""Learn from what reviewers did in the console.

    python -m evals.eval_approvals

Compares every reviewed judgment call with what Claude proposed (approved as-is,
draft rewritten, action changed, rejected) and reports agreement by confidence.
Every case where the reviewer chose a different action is written to
evals/results/approval_cases.json in scenario format, so the next
`python -m evals.eval_scenarios --include-approvals` tests the model against
the reviewer's call. That's the loop: corrections become regression tests.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from margin_guard import db
from margin_guard.config import DB_PATH

RESULTS_DIR = Path(__file__).resolve().parent / "results"
BUCKETS = [(0.0, 0.7), (0.7, 0.85), (0.85, 0.95), (0.95, 1.01)]


def usd(v: float) -> str:
    return f"${v:,.0f}"


def classify(p) -> str:
    if p["status"] == "rejected":
        return "rejected"
    if p["final_action"] and p["final_action"] != p["action"]:
        return "action_changed"
    if p["status"] == "edited":
        return "draft_rewritten"
    return "approved_as_is"


def review_outcomes(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM proposals WHERE kind = 'quote_action' AND decided_by = 'llm'
           AND status IN ('approved', 'edited', 'rejected') ORDER BY reviewed_at"""
    ).fetchall()
    return [{**dict(r), "facts": json.loads(r["facts"]), "outcome": classify(r)} for r in rows]


def learned_cases(outcomes: list[dict]) -> list[dict]:
    """Reviewer overrides that become scenarios (only actions Claude can choose)."""
    cases = []
    for o in outcomes:
        if o["outcome"] != "action_changed" or o["final_action"] not in ("reprice", "contact_customer"):
            continue
        f = o["facts"]
        cases.append({
            "id": f"A{o['id']}",
            "group": "from_approvals",
            "description": f"{f['quote_id']} {f['customer_name']}: Claude said {o['action']}, "
                           f"reviewer chose {o['final_action']}" + (f" ({o['reviewer_note']})" if o["reviewer_note"] else ""),
            "expected": o["final_action"],
            "facts": f,
            "checks": [],
        })
    return cases


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    conn = db.connect(args.db)
    outcomes = review_outcomes(conn)
    rules = Counter(r["status"] for r in conn.execute(
        "SELECT status FROM proposals WHERE kind = 'quote_action' AND decided_by = 'rule'"
        " AND status IN ('approved', 'edited', 'rejected')"))
    conn.close()

    RESULTS_DIR.mkdir(exist_ok=True)
    cases = learned_cases(outcomes)
    (RESULTS_DIR / "approval_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")

    n = len(outcomes)
    counts = Counter(o["outcome"] for o in outcomes)
    lines = [f"### Reviewer verdicts on Claude's judgment calls ({n} reviewed)", ""]
    if not n:
        lines.append("Nothing reviewed yet. Approve, edit or reject some cards in the console first.")
    else:
        lines += ["| Outcome | Count | Share |", "|---|---|---|"]
        for k in ("approved_as_is", "draft_rewritten", "action_changed", "rejected"):
            lines.append(f"| {k.replace('_', ' ')} | {counts[k]} | {counts[k] / n:.0%} |")
        lines += ["", "| Confidence | Reviewed | Action kept |", "|---|---|---|"]
        for lo, hi in BUCKETS:
            inb = [o for o in outcomes if lo <= (o["confidence"] or 0) < hi]
            kept = sum(o["outcome"] in ("approved_as_is", "draft_rewritten") for o in inb)
            lines.append(f"| {lo:.2f}-{min(hi, 1.0):.2f} | {len(inb)} | {f'{kept / len(inb):.0%}' if inb else '-'} |")
    # Overrides to an action the policy never lets Claude pick below the floor
    # (absorb/honor) aren't model errors; they say the *policy* may be wrong.
    policy_signals = [o for o in outcomes if o["outcome"] == "action_changed"
                      and o["final_action"] not in ("reprice", "contact_customer")]
    lines += ["", f"Rule decisions reviewed: {sum(rules.values())} "
                  f"({rules['approved']} confirmed, {rules['edited']} changed, {rules['rejected']} rejected)",
              f"New regression cases written: **{len(cases)}** -> evals/results/approval_cases.json"]
    if policy_signals:
        lines += ["", f"**Policy signals ({len(policy_signals)}):** the reviewer chose an action the policy doesn't "
                      "allow below the floor, so this isn't a model error to fix with a test; it suggests a rule change."]
        for o in policy_signals:
            f = o["facts"]
            lines.append(f"- {f['quote_id']} {f['customer_name']}: {o['final_action']} instead of {o['action']} "
                         f"on a {usd(f['quote_value_usd'])} quote with {usd(f['exposure_usd'])} at risk"
                         + (f" ({o['reviewer_note']})" if o["reviewer_note"] else ""))
        small = [o["facts"]["exposure_usd"] for o in policy_signals if o["final_action"] == "absorb"]
        if small:
            lines.append(f"- Pattern to watch: absorbing increases up to {usd(max(small))} at risk. If it repeats, "
                         "a de-minimis rule (absorb below $X exposure) would take these off the queue.")
    disagreements = [o for o in outcomes if o["outcome"] in ("action_changed", "rejected")]
    if disagreements:
        lines += ["", "| Quote | Claude | Reviewer | Conf. | Note |", "|---|---|---|---|---|"]
        for o in disagreements:
            lines.append(f"| {o['quote_id']} {o['facts']['customer_name']} | {o['action']} "
                         f"| {o['final_action'] or 'rejected'} | {(o['confidence'] or 0):.2f} | {o['reviewer_note'] or ''} |")

    report = "\n".join(lines)
    print(report)
    (RESULTS_DIR / "approval_report.md").write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
