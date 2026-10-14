"""Extra shops for human review sessions, and export of what the reviewer did.

    python -m evals.promotion.review_shop build --seeds 43 44 45   # ~20 judgment cards each, ~$0.20 per shop
    python -m evals.promotion.review_shop export                    # -> evals/results/promotion/reviews_human.json

Each shop is a different seed (same catalog, customers and inbox; different open
quotes), processed with Claude exactly as the console would. Shop 42 is the gate's
replay set, so review shops start at 43 and never overlap it. Review a shop in the
console by pointing it at the database:

    $env:MG_DB_PATH = "data/review_shops/shop_43.db"; uvicorn margin_guard.api:app --port 8000

The export is the recorded reviewer behavior the personas and the simulated
reviewer are built from (and checked against, on held-out reviews).
"""

import argparse
import json
from pathlib import Path

from evals.eval_approvals import classify
from margin_guard import db
from margin_guard.config import ROOT
from margin_guard.decide import llm_decide

from .shops import build_processed_shop

SHOPS_DIR = ROOT / "data" / "review_shops"
EXPORT = Path(__file__).resolve().parent.parent / "results" / "promotion" / "reviews_human.json"


def shop_path(rng_seed: int) -> Path:
    return SHOPS_DIR / f"shop_{rng_seed}.db"


def build(seeds: list[int], reset: bool) -> None:
    SHOPS_DIR.mkdir(parents=True, exist_ok=True)
    for s in seeds:
        if s == 42:
            raise SystemExit("Shop 42 is the gate's replay set; review shops start at 43.")
        path = shop_path(s)
        if path.exists():
            if not reset:
                print(f"shop {s}: {path} exists (pass --reset to rebuild; that discards its reviews)")
                continue
            path.unlink()
        conn = db.connect(path)
        build_processed_shop(conn, s, llm_decide)
        n = dict(conn.execute(
            """SELECT decided_by, COUNT(*) FROM proposals WHERE kind = 'quote_action' AND status = 'pending'
               GROUP BY decided_by""").fetchall())
        conn.close()
        print(f"shop {s}: {n.get('llm', 0)} judgment cards, {n.get('rule', 0)} rule cards, "
              f"{n.get('error', 0)} escalated -> {path}")


def export() -> list[dict]:
    rows = []
    for path in sorted(SHOPS_DIR.glob("shop_*.db")):
        seed_no = int(path.stem.split("_")[1])
        conn = db.connect(path)
        for p in conn.execute(
                """SELECT * FROM proposals WHERE kind = 'quote_action'
                   AND status IN ('approved', 'edited', 'rejected') ORDER BY reviewed_at, id"""):
            rows.append({
                "id": f"R{seed_no}-{p['id']}", "shop": seed_no, "proposal_id": p["id"],
                "decided_by": p["decided_by"], "rule_id": p["rule_id"],
                "proposed": p["action"], "confidence": p["confidence"],
                "outcome": classify(p), "final_action": p["final_action"],
                "draft_rewritten": p["status"] == "edited" and p["final_action"] == p["action"],
                "note": p["reviewer_note"], "reviewed_at": p["reviewed_at"],
                "facts": json.loads(p["facts"]),
            })
        conn.close()
    EXPORT.parent.mkdir(parents=True, exist_ok=True)
    EXPORT.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--seeds", type=int, nargs="+", default=[43, 44, 45])
    b.add_argument("--reset", action="store_true")
    sub.add_parser("export")
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.seeds, args.reset)
    else:
        rows = export()
        llm_rows = [r for r in rows if r["decided_by"] == "llm"]
        changed = sum(r["outcome"] == "action_changed" for r in rows)
        print(f"Exported {len(rows)} reviews ({len(llm_rows)} judgment calls, {changed} action changes) -> {EXPORT}")


if __name__ == "__main__":
    main()
