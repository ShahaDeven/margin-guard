"""The replay set: 30 hand-built scenarios + the 32 judgment calls from the seeded shop (seed 42).

The shop cases are a snapshot of recorded facts (data/replay_cases_shop.json), so a
replay forks the recorded world at the decision step: extraction and impact are held
fixed and only the decision reruns. Rebuild the snapshot (offline, no API calls) with

    python -m evals.promotion.cases --snapshot

Each case carries its answer under the current policy (`expected`): a scenario's
hand-written gold, or the reference policy for a shop case (how eval_decisions
scores them; its note table is keyed by the shop's real customer IDs, so it can't
score the scenarios). Candidates derive their own answer keys from it.
"""

import argparse
import json
import tempfile
from pathlib import Path

from evals.reference_policy import expected_action
from evals.scenarios import scenarios
from margin_guard import db
from margin_guard.config import ROOT
from margin_guard.decide import QuoteDecision

from .shops import build_processed_shop

SHOP_SNAPSHOT = ROOT / "data" / "replay_cases_shop.json"
SHOP_SEED = 42


def _stand_in(facts: dict) -> QuoteDecision:
    # The facts don't depend on the decider; this only lets the coordinator finish offline.
    return QuoteDecision(action=expected_action(facts), confidence=0.9, rationale="snapshot",
                         email_subject="-", email_body="-")


def snapshot_shop() -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        conn = db.connect(Path(tmp) / "snapshot.db")
        build_processed_shop(conn, SHOP_SEED, _stand_in)
        rows = conn.execute(
            "SELECT id, quote_id, facts, status FROM proposals"
            " WHERE kind = 'quote_action' AND decided_by = 'llm' ORDER BY event_id, quote_id").fetchall()
        conn.close()
    cases = []
    for r in rows:
        f = json.loads(r["facts"])
        cases.append({
            "id": f"SH-{f['quote_id'][-4:]}-{f['material_id'].removeprefix('MAT-')}",
            "group": "shop",
            "description": f"{f['quote_id']} {f['customer_name']} ({f['customer_tier']}), ${f['quote_value_usd']:,.0f}, "
                           f"${f['exposure_usd']:,.2f} at risk" + (" [superseded]" if r["status"] == "superseded" else ""),
            "facts": f,
            "checks": [],
        })
    return cases


def replay_cases() -> list[dict]:
    if not SHOP_SNAPSHOT.exists():
        raise SystemExit(f"{SHOP_SNAPSHOT.name} missing; run `python -m evals.promotion.cases --snapshot`.")
    shop = json.loads(SHOP_SNAPSHOT.read_text(encoding="utf-8"))
    keep = ("id", "group", "description", "facts", "checks", "expected")
    return ([{k: s[k] for k in keep} for s in scenarios()]
            + [{**c, "expected": expected_action(c["facts"])} for c in shop])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--snapshot", action="store_true", help=f"rebuild {SHOP_SNAPSHOT.name}")
    args = ap.parse_args()
    if args.snapshot:
        cases = snapshot_shop()
        SHOP_SNAPSHOT.write_text(json.dumps(cases, indent=2), encoding="utf-8")
        print(f"Wrote {len(cases)} shop cases to {SHOP_SNAPSHOT}")
    cases = replay_cases()
    print(f"{len(cases)} replay cases: " + ", ".join(
        f"{g} {sum(c['group'] == g for c in cases)}" for g in dict.fromkeys(c["group"] for c in cases)))


if __name__ == "__main__":
    main()
