"""The correction ledger: every proposed change, why it was proposed, and what happened to it.

    python -m evals.promotion.ledger     # -> evals/results/promotion/ledger.json + ledger.md

A correction (a reviewer override, an eval miss) becomes an entry. An entry answers
two separate questions, because the gate can only answer one of them:

    safe     the promotion gate's verdict on the replays (v3, K=8), linked to the report
    wanted   what the reviews say: how many reviewed cards support the change, how many
             contradict it (a reviewer who saw the case and chose otherwise)

    proposed   no candidate replayed yet
    rejected   the gate found a regression
    held       the gate needs more replays, or the change is safe but reviews don't back it
    promoted   safe, and either backed by reviews or not a question reviews can answer

The ledger is append-only. Each run recomputes every entry; when an entry's status or
evidence changes, a new version is added with the date and the reason, and earlier
versions stay. Re-run after new reviews or replays and the history shows what moved.
"""

import json
from dataclasses import dataclass
from datetime import date
from typing import Callable

from evals.reference_policy import expected_action

from .candidates import DE_MINIMIS_USD
from .cases import replay_cases
from .curve import gate_results
from .replay import DEFAULT_K, OUT_DIR

LEDGER_JSON = OUT_DIR / "ledger.json"
LEDGER_MD = OUT_DIR / "ledger.md"
REVIEWS = OUT_DIR / "reviews_human.json"
REPORT_LINK = "promotion_report.md"
MIN_SUPPORT = 2          # reviews backing a policy change before "wanted" counts as yes

Review = dict
# review -> "support" | "contradict" | None (the review says nothing about this change)
Matcher = Callable[[Review], str | None]


def _final(r: Review) -> str:
    return r["final_action"] or r["proposed"]


def de_minimis_evidence(r: Review) -> str | None:
    """A reviewed card under the line: absorbing it supports the rule, anything else contradicts it."""
    if r["facts"]["exposure_usd"] >= DE_MINIMIS_USD or r["outcome"] == "rejected":
        return None
    return "support" if _final(r) == "absorb" else "contradict"


def conditional_note_evidence(r: Review) -> str | None:
    """Cards whose note sets its own call condition: did the reviewer follow the written policy?"""
    note = (r["facts"].get("contract_note") or "").lower()
    if "over $" not in note or r["outcome"] == "rejected":
        return None
    return "support" if _final(r) == expected_action(r["facts"]) else "contradict"


def any_note_call_evidence(r: Review) -> str | None:
    """Cards with a contract note where the written policy says email: did the reviewer call anyway?

    Cards the policy already sends to a call ($15k+, key accounts, call notes) say nothing
    about whether a note on its own should, so they don't count either way."""
    if not r["facts"].get("contract_note") or r["outcome"] == "rejected" or expected_action(r["facts"]) != "reprice":
        return None
    return {"contact_customer": "support", "reprice": "contradict"}.get(_final(r))


@dataclass(frozen=True)
class Proposal:
    id: str
    title: str
    source: str                       # the correction that started it
    candidate: str | None             # the replayed candidate, if one was built
    kind: str                         # rule | policy_text | model_swap | control
    evidence: Matcher | None = None   # None: reviews can't speak to it (a control, a model swap)
    seed_support: int = 0             # supporting corrections from before the review sessions
    note: str = ""


PROPOSALS = [
    Proposal("L-001", "De-minimis rule as code: absorb under $50 at risk",
             "Reviewer override on Q-2026-0169 (main shop): absorbed a ~$30 increase Claude sent to a call.",
             "C1a", "rule", de_minimis_evidence, seed_support=1),
    Proposal("L-002", "De-minimis rule as policy text",
             "Same override as L-001, written into the prompt instead of code.",
             "C1b", "policy_text", de_minimis_evidence, seed_support=1),
    Proposal("L-003", "Clarify notes that set their own call condition",
             "Eval miss: S24 (key account, $8k, 'call over $10k') wrong 3/3 runs at confidence 0.55-0.60.",
             "C2", "policy_text", conditional_note_evidence),
    Proposal("L-004", "Tidy-up: soften the contract-note override",
             "Control: built to look harmless and be wrong.", "C3a", "control"),
    Proposal("L-005", "Tidy-up: drop the contract-note override",
             "Control: built to look harmless and be wrong.", "C3b", "control"),
    Proposal("L-006", "Swap Sonnet for Haiku (~15x cheaper)",
             "Cost: distill onto a cheaper model if nothing regresses.", "C4", "model_swap"),
    Proposal("L-007", "Call the customer whenever any contract note exists",
             "Pattern in the review sessions: overrides moved emails to calls on cards with contract notes, "
             "including notes about shipping and payment terms.",
             None, "policy_text", any_note_call_evidence,
             note="Conflicts with the written policy, which says notes that aren't about price "
                  "communication must not change the decision. Needs a candidate and a gate run before anything else."),
]


def wanted(p: Proposal, reviews: list[Review]) -> dict:
    if p.evidence is None:
        return {"applies": False, "support": 0, "contradict": 0, "examples": []}
    hits = [(r, p.evidence(r)) for r in reviews]
    hits = sorted(((r, v) for r, v in hits if v), key=lambda h: h[0]["outcome"] != "action_changed")  # overrides first
    support = p.seed_support + sum(v == "support" for _, v in hits)
    contradict = sum(v == "contradict" for _, v in hits)
    examples = [f"{v}: {r['facts']['quote_id']} {r['facts']['customer_name']}, "
                f"${r['facts']['exposure_usd']:,.2f} at risk, proposed {r['proposed']}, reviewer {_final(r)}"
                + (f" (\"{r['note']}\")" if r.get("note") else "") for r, v in hits][:6]
    return {"applies": True, "support": support, "contradict": contradict, "examples": examples}


def status(safe: dict | None, want: dict) -> tuple[str, str]:
    """(status, reason) from the gate verdict and the review evidence."""
    if safe is None:
        return "proposed", "no candidate replayed yet"
    if safe["verdict"] == "reject":
        return "rejected", "the gate found regressions: " + "; ".join(safe["reasons"])
    if safe["verdict"] == "hold":
        return "held", "the gate needs more replays: " + "; ".join(safe["reasons"])
    if not want["applies"]:
        return "promoted", "safe; reviews don't speak to this kind of change"
    if want["support"] >= MIN_SUPPORT and want["support"] > want["contradict"]:
        return "promoted", f"safe, and backed by {want['support']} reviews against {want['contradict']}"
    return "held", (f"safe to promote, but not wanted: {want['support']} review(s) support it, "
                    f"{want['contradict']} contradict it")


def compute(reviews: list[Review], gate_by_candidate: dict) -> list[dict]:
    entries = []
    for p in PROPOSALS:
        g = gate_by_candidate.get(p.candidate) if p.candidate else None
        safe = None if g is None else {
            "verdict": g.verdict, "gate": "v3", "k": DEFAULT_K, "reasons": g.reasons, "counts": g.counts,
            "accuracy": [round(g.accuracy_base, 4), round(g.accuracy_cand, 4)], "report": REPORT_LINK}
        want = wanted(p, reviews)
        st, why = status(safe, want)
        entries.append({"id": p.id, "title": p.title, "source": p.source, "candidate": p.candidate,
                        "kind": p.kind, "note": p.note, "safe": safe, "wanted": want,
                        "status": st, "reason": why})
    return entries


def _fingerprint(e: dict) -> str:
    """What counts as a change worth a new version: status, verdict and evidence counts."""
    safe = e["safe"] or {}
    return json.dumps([e["status"], safe.get("verdict"), safe.get("counts"),
                       e["wanted"]["support"], e["wanted"]["contradict"]], sort_keys=True)


def merge(ledger: dict, entries: list[dict], today: str) -> dict:
    """Append a version to every entry whose status or evidence moved; never rewrite history."""
    by_id = {e["id"]: e for e in ledger.get("entries", [])}
    out = []
    for e in entries:
        old = by_id.get(e["id"])
        versions = list(old["versions"]) if old else []
        if not versions or versions[-1]["fingerprint"] != _fingerprint(e):
            versions.append({"version": len(versions) + 1, "date": today, "status": e["status"],
                             "reason": e["reason"], "fingerprint": _fingerprint(e)})
        out.append({**e, "versions": versions})
    return {"updated": today, "entries": out}


def render(ledger: dict) -> str:
    L = ["# Correction ledger", "",
         "Every proposed change, the correction it came from, and two separate questions: is it **safe** "
         f"(the promotion gate, v3 at K = {DEFAULT_K}, [report]({REPORT_LINK})) and is it **wanted** (what reviewers "
         "did on cards it would change). Generated by `python -m evals.promotion.ledger`; append-only.", "",
         "| Entry | Change | Safe (gate) | Wanted (reviews) | Status |", "|---|---|---|---|---|"]
    for e in ledger["entries"]:
        safe = e["safe"]["verdict"] if e["safe"] else "not replayed"
        w = e["wanted"]
        want = f"{w['support']} for / {w['contradict']} against" if w["applies"] else "n/a"
        L.append(f"| {e['id']} | {e['title']} | {safe} | {want} | **{e['status']}** |")
    for e in ledger["entries"]:
        L += ["", f"## {e['id']}: {e['title']}", "",
              f"- **Source:** {e['source']}",
              f"- **Kind:** {e['kind']}" + (f", candidate `{e['candidate']}`" if e["candidate"] else ""),
              f"- **Status:** {e['status']} ({e['reason']})"]
        if e["note"]:
            L.append(f"- **Note:** {e['note']}")
        if e["safe"]:
            c = e["safe"]["counts"]
            L.append(f"- **Gate:** {e['safe']['verdict']}; fixed {c['fixed']}, regressed {c['regressed']}, "
                     f"flaky {c['flaky']}; accuracy {e['safe']['accuracy'][0]:.1%} → {e['safe']['accuracy'][1]:.1%}")
        if e["wanted"]["examples"]:
            L.append("- **Review evidence:**")
            L += [f"  - {x}" for x in e["wanted"]["examples"]]
        L.append("- **History:** " + "; ".join(f"v{v['version']} {v['date']} {v['status']}" for v in e["versions"]))
    return "\n".join(L) + "\n"


def main() -> None:
    reviews = json.loads(REVIEWS.read_text(encoding="utf-8")) if REVIEWS.exists() else []
    gate_by_candidate, _ = gate_results(replay_cases())
    old = json.loads(LEDGER_JSON.read_text(encoding="utf-8")) if LEDGER_JSON.exists() else {}
    ledger = merge(old, compute(reviews, gate_by_candidate), date.today().isoformat())
    LEDGER_JSON.write_text(json.dumps(ledger, indent=1), encoding="utf-8")
    LEDGER_MD.write_text(render(ledger), encoding="utf-8")
    for e in ledger["entries"]:
        print(f"{e['id']}  {e['status']:<9} {e['title']}")
    print(f"Wrote {LEDGER_JSON} and {LEDGER_MD}")


if __name__ == "__main__":
    main()
