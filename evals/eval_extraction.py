"""Score email -> event extraction against gold labels.

    python -m evals.eval_extraction                 # the 15 inbox emails (the set the pipeline was built on)
    python -m evals.eval_extraction --set holdout   # 10 harder emails nothing was tuned against
    python -m evals.eval_extraction --replay        # rescore cached extractions, no API calls

Builds a throwaway database each run so results never depend on local state.
"""

import argparse
import json
import tempfile
from pathlib import Path

from margin_guard import db, ingest, seed
from margin_guard.config import EMAILS_PATH, MODEL, ROOT
from margin_guard.parser import EmailExtraction

RESULTS_DIR = Path(__file__).resolve().parent / "results"
SETS = {
    # name: (emails, cache of raw extractions, report suffix)
    "tuned": (EMAILS_PATH, RESULTS_DIR / "extractions.json", ""),
    "holdout": (ROOT / "data" / "vendor_emails_holdout.json", RESULTS_DIR / "extractions_holdout.json", "_holdout"),
}
PRICE_TOLERANCE = 0.005   # 0.5%


def _score_changes(gold_changes, predicted):
    """Match gold changes to predicted detected events by material."""
    rows = []
    by_material = {p["material_id"]: p for p in predicted}
    for g in gold_changes:
        p = by_material.pop(g["material_id"], None)
        price_ok = bool(p and p["new_cost_per_lb"] is not None
                        and abs(p["new_cost_per_lb"] - g["new_cost_per_lb"]) <= PRICE_TOLERANCE * g["new_cost_per_lb"])
        date_ok = bool(p and p["effective_date"] == g["effective_date"])
        rows.append({"material_id": g["material_id"], "found": p is not None,
                     "price_ok": price_ok, "date_ok": date_ok,
                     "predicted_cost": p["new_cost_per_lb"] if p else None,
                     "gold_cost": g["new_cost_per_lb"]})
    extra = list(by_material)    # predicted changes with no gold counterpart
    return rows, extra


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--replay", action="store_true", help="reuse cached extractions instead of calling Claude")
    ap.add_argument("--set", choices=sorted(SETS), default="tuned")
    args = ap.parse_args()
    emails_path, CACHE_PATH, suffix = SETS[args.set]

    gold = {e["id"]: e for e in json.loads(emails_path.read_text(encoding="utf-8"))}
    RESULTS_DIR.mkdir(exist_ok=True)

    extract = None
    if args.replay:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        extract = lambda email: EmailExtraction.model_validate(cache[email["id"]])  # noqa: E731

    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "eval.db")
        seed.build(conn, emails_path)
        print(f"[{args.set}] Extracting {len(gold)} emails ({'replay' if args.replay else MODEL})")
        outcomes = ingest.run(conn, extract=extract) if extract else ingest.run(conn)

        if not args.replay:
            cache = {r["id"]: json.loads(r["extraction"])
                     for r in conn.execute("SELECT id, extraction FROM inbox_emails WHERE extraction IS NOT NULL")}
            CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

        per_email = []
        for email_id, g in gold.items():
            predicted = [json.loads(r["payload"]) for r in conn.execute(
                "SELECT payload FROM events WHERE source_ref = ? AND event_type = 'price_change.detected'",
                (f"email:{email_id}",))]
            gold_changes = g["gold"]["changes"] if g["gold"]["outcome"] == "detected" else []
            changes, extra = _score_changes(gold_changes, predicted)
            per_email.append({
                "id": email_id, "trap": g["gold"]["trap"],
                "gold_outcome": g["gold"]["outcome"], "outcome": outcomes.get(email_id),
                "outcome_ok": outcomes.get(email_id) == g["gold"]["outcome"],
                "changes": changes, "unexpected_changes": extra,
            })
        conn.close()

    n = len(per_email)
    all_changes = [c for e in per_email for c in e["changes"]]
    n_changes = len(all_changes)
    false_pos = sum(len(e["unexpected_changes"]) for e in per_email)
    summary = {
        "set": args.set,
        "model": "replay" if args.replay else MODEL,
        "emails": n,
        "outcome_accuracy": sum(e["outcome_ok"] for e in per_email) / n,
        "gold_changes": n_changes,
        "change_recall": sum(c["found"] for c in all_changes) / n_changes,
        "price_accuracy": sum(c["price_ok"] for c in all_changes) / n_changes,
        "date_accuracy": sum(c["date_ok"] for c in all_changes) / n_changes,
        "unexpected_changes": false_pos,
    }

    lines = ["| Email | Trap | Gold | Got | Changes (material / $/lb / date) |", "|---|---|---|---|---|"]
    for e in per_email:
        mark = "PASS" if e["outcome_ok"] else "FAIL"
        yn = lambda ok: "y" if ok else "n"  # noqa: E731
        detail = "; ".join(
            f"{c['material_id']} {yn(c['found'])}/{yn(c['price_ok'])}/{yn(c['date_ok'])}"
            for c in e["changes"]) or "-"
        if e["unexpected_changes"]:
            detail += f" | unexpected: {', '.join(map(str, e['unexpected_changes']))}"
        lines.append(f"| {e['id']} | {e['trap']} | {e['gold_outcome']} | {mark} {e['outcome']} | {detail} |")
    lines += [
        "",
        f"- Outcome accuracy: **{summary['outcome_accuracy']:.0%}** ({n} emails)",
        f"- Change recall: **{summary['change_recall']:.0%}**, price within 0.5%: **{summary['price_accuracy']:.0%}**, "
        f"date exact: **{summary['date_accuracy']:.0%}** ({n_changes} gold changes)",
        f"- Unexpected changes emitted: **{false_pos}**",
    ]
    report = "\n".join(lines)
    print("\n" + report)
    (RESULTS_DIR / f"extraction_report{suffix}.md").write_text(report + "\n", encoding="utf-8")
    (RESULTS_DIR / f"extraction_results{suffix}.json").write_text(
        json.dumps({"summary": summary, "emails": per_email}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
