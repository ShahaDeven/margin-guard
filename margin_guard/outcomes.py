"""What the customer did after a price increase went out.

The system works out the impact, decides and drafts; a person approves; then the customer
answers. Until that answer is on record, nobody can say whether repricing worked. An outcome
closes the loop on an approved reprice (an email) or call, the two decisions that ask the
customer for more money:

    accepted     the customer took the revised prices; they are written to the quote
                 (a reprice already wrote them; a call writes them now)
    negotiated   the customer took part of the increase; each line moves by the same share
                 of its increase, so the quote shows the prices actually agreed
    lost         the customer walked; the quote is marked lost and its value counted

Every outcome can be undone, and undo refuses if the quote has changed since, the same way
undoing a decision does.

Outcomes feed what people read, never what the model reads: the owner's figures (recovered
of asked, revenue lost) and each customer's record on the decision cards ("2 of 3 increases
negotiated down"). Keeping them out of the decision facts keeps every cached decision and
eval valid; whether a customer's record should change the decision is a policy change, and
would go through the promotion gate like any other.

    python -m margin_guard.outcomes           # the summary in the terminal
"""

import argparse
import json
import sqlite3
from datetime import date
from decimal import Decimal

from . import db
from .config import AS_OF
from .money import D, ZERO, cents, out, price

CUSTOMER_FACING = {"reprice": "email", "contact_customer": "call"}
OUTCOMES = ("accepted", "negotiated", "lost")


class OutcomeError(ValueError):
    pass


def asked(facts: dict) -> Decimal:
    """The increase the decision asked for, over the whole quote."""
    return cents(sum((D(ln["proposed_unit_price"]) - D(ln["unit_price"])) * ln["qty"] for ln in facts["lines"]))


def _decision(conn: sqlite3.Connection, proposal_id: int) -> sqlite3.Row:
    p = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if p is None:
        raise OutcomeError(f"proposal {proposal_id} not found")
    if p["kind"] != "quote_action" or p["status"] not in ("approved", "edited"):
        raise OutcomeError("only an approved decision has a customer response to record")
    if p["final_action"] not in CUSTOMER_FACING:
        raise OutcomeError("only a reprice or a call asks the customer for anything")
    return p


def record(conn: sqlite3.Connection, proposal_id: int, outcome: str, *, recovered_usd: float | str | None = None,
           on: str | None = None, note: str | None = None) -> dict:
    p = _decision(conn, proposal_id)
    if outcome not in OUTCOMES:
        raise OutcomeError(f"unknown outcome {outcome!r}")
    if conn.execute("SELECT 1 FROM quote_outcomes WHERE proposal_id = ?", (proposal_id,)).fetchone():
        raise OutcomeError("this decision already has the customer's response; undo it first")
    on = on or AS_OF.isoformat()
    try:
        date.fromisoformat(on)
    except ValueError:
        raise OutcomeError(f"{on!r} is not a date (YYYY-MM-DD)") from None

    facts = json.loads(p["facts"])
    action = p["final_action"]
    quote = conn.execute("SELECT status FROM quotes WHERE id = ?", (p["quote_id"],)).fetchone()
    if quote["status"] != "open":
        raise OutcomeError(f"quote {p['quote_id']} is already {quote['status']}")
    ask = asked(facts)
    current = {r["id"]: D(r["unit_price"]) for r in conn.execute(
        "SELECT id, unit_price FROM quote_lines WHERE quote_id = ?", (p["quote_id"],))}

    # The quote must still hold the prices this decision left it with.
    for ln in facts["lines"]:
        expected = D(ln["proposed_unit_price"] if action == "reprice" else ln["unit_price"])
        if current.get(ln["line_id"]) != expected:
            raise OutcomeError(f"quote {p['quote_id']} has been revised since this decision; "
                               "record the response on the latest one")

    changes: list[dict] = []
    recovered = lost_revenue = ZERO
    prior_status = None
    if outcome == "lost":
        lost_revenue = cents(sum(current[ln_id] * qty for ln_id, qty in conn.execute(
            "SELECT id, qty FROM quote_lines WHERE quote_id = ?", (p["quote_id"],))))
        prior_status = "open"
        conn.execute("UPDATE quotes SET status = 'lost' WHERE id = ?", (p["quote_id"],))
    else:
        if outcome == "accepted":
            share = Decimal(1)
        else:
            if recovered_usd in (None, ""):
                raise OutcomeError(f"say how much of the ${ask:,.2f} increase the customer agreed to")
            try:
                agreed = cents(D(str(recovered_usd)))
            except Exception:
                raise OutcomeError(f"{recovered_usd!r} is not an amount") from None
            if not ZERO < agreed < ask:
                raise OutcomeError(f"a negotiated increase is more than $0 and less than the ${ask:,.2f} asked; "
                                   "otherwise record it as accepted or lost")
            share = agreed / ask
        for ln in facts["lines"]:
            before = D(ln["unit_price"])
            new = price(before + (D(ln["proposed_unit_price"]) - before) * share)
            if new != current[ln["line_id"]]:
                conn.execute("UPDATE quote_lines SET unit_price = ? WHERE id = ?", (new, ln["line_id"]))
                changes.append({"line_id": ln["line_id"], "before": out(current[ln["line_id"]]), "after": out(new)})
            recovered += (new - before) * ln["qty"]
        recovered = cents(recovered)        # what the agreed unit prices actually bring in

    cur = conn.execute(
        """INSERT INTO quote_outcomes (proposal_id, quote_id, customer_id, channel, outcome, asked_usd, recovered_usd,
           lost_revenue_usd, outcome_date, note, price_changes, prior_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (proposal_id, p["quote_id"], facts["customer_id"], CUSTOMER_FACING[action], outcome, ask, recovered,
         lost_revenue, on, note, json.dumps(changes), prior_status))
    conn.commit()
    return get(conn, cur.lastrowid)


def undo(conn: sqlite3.Connection, outcome_id: int) -> None:
    row = conn.execute("SELECT * FROM quote_outcomes WHERE id = ?", (outcome_id,)).fetchone()
    if row is None:
        raise OutcomeError(f"outcome {outcome_id} not found")
    if row["source"] != "console":
        raise OutcomeError("history from before Margin Guard can't be undone here")
    changes = json.loads(row["price_changes"] or "[]")
    for ch in changes:
        now = conn.execute("SELECT unit_price FROM quote_lines WHERE id = ?", (ch["line_id"],)).fetchone()
        if D(now["unit_price"]) != D(ch["after"]):
            raise OutcomeError(f"quote {row['quote_id']} has been revised since; undo that first")
    if row["prior_status"]:
        status = conn.execute("SELECT status FROM quotes WHERE id = ?", (row["quote_id"],)).fetchone()["status"]
        if status != "lost":
            raise OutcomeError(f"quote {row['quote_id']} is now {status}; undo that first")
        conn.execute("UPDATE quotes SET status = ? WHERE id = ?", (row["prior_status"], row["quote_id"]))
    for ch in changes:
        conn.execute("UPDATE quote_lines SET unit_price = ? WHERE id = ?", (ch["before"], ch["line_id"]))
    conn.execute("DELETE FROM quote_outcomes WHERE id = ?", (outcome_id,))
    conn.commit()


def get(conn: sqlite3.Connection, outcome_id: int) -> dict:
    row = conn.execute("SELECT * FROM quote_outcomes WHERE id = ?", (outcome_id,)).fetchone()
    return _row(row)


def _row(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["price_changes"] = json.loads(d["price_changes"] or "[]")
    return d


def for_proposals(conn: sqlite3.Connection, proposal_ids: list[int]) -> dict[int, dict]:
    if not proposal_ids:
        return {}
    marks = ",".join("?" * len(proposal_ids))
    return {r["proposal_id"]: _row(r) for r in conn.execute(
        f"SELECT * FROM quote_outcomes WHERE proposal_id IN ({marks})", proposal_ids)}


# ------------------------------------------------------------------ what people read


def _tally(rows) -> dict:
    """Counts and dollars. `kept` is the share of the increase customers agreed to on the jobs
    they stayed on; a lost job's ask isn't in it (its cost is the revenue, counted separately)."""
    t = {"requests": 0, "accepted": 0, "negotiated": 0, "lost": 0,
         "asked_usd": ZERO, "asked_kept_jobs_usd": ZERO, "recovered_usd": ZERO, "lost_revenue_usd": ZERO}
    for r in rows:
        t["requests"] += 1
        t[r["outcome"]] += 1
        t["asked_usd"] += D(r["asked_usd"])
        if r["outcome"] != "lost":
            t["asked_kept_jobs_usd"] += D(r["asked_usd"])
        t["recovered_usd"] += D(r["recovered_usd"])
        t["lost_revenue_usd"] += D(r["lost_revenue_usd"])
    base = t["asked_kept_jobs_usd"]
    kept = t["recovered_usd"] / base if base else None
    money = ("asked_usd", "asked_kept_jobs_usd", "recovered_usd", "lost_revenue_usd")
    return {**t, **{k: out(cents(t[k])) for k in money},
            "kept": out(kept.quantize(Decimal("0.0001"))) if kept is not None else None}


def pattern(t: dict) -> str:
    """One plain phrase for how a customer has taken increases; never a score."""
    n = t["requests"]
    if n < 2:
        return "too few increases to say"
    if t["lost"] and t["lost"] / n >= 1 / 3:
        return "has walked over increases"
    if (t["negotiated"] + t["lost"]) * 2 >= n:
        return "usually pushes back"
    return "usually accepts"


def customer_records(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM quote_outcomes ORDER BY outcome_date, id").fetchall()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r["customer_id"], []).append(r)
    records = {}
    for cid, rs in by.items():
        t = _tally(rs)
        last = rs[-1]
        records[cid] = t | {"pattern": pattern(t),
                            "last": {"outcome": last["outcome"], "date": last["outcome_date"], "quote_id": last["quote_id"]}}
    return records


def summary(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT * FROM quote_outcomes").fetchall()
    awaiting = []
    for p in conn.execute(
            """SELECT p.id, p.quote_id, p.final_action, p.reviewed_at, p.facts, q.status AS quote_status
               FROM proposals p JOIN quotes q ON q.id = p.quote_id
               LEFT JOIN quote_outcomes o ON o.proposal_id = p.id
               WHERE p.kind = 'quote_action' AND p.status IN ('approved', 'edited')
                 AND p.final_action IN ('reprice', 'contact_customer') AND o.id IS NULL
               ORDER BY p.reviewed_at, p.id"""):
        f = json.loads(p["facts"])
        awaiting.append({"proposal_id": p["id"], "quote_id": p["quote_id"], "customer_id": f["customer_id"],
                         "customer_name": f["customer_name"], "channel": CUSTOMER_FACING[p["final_action"]],
                         "asked_usd": out(asked(f)), "quote_value_usd": f["quote_value_usd"],
                         "reviewed_at": p["reviewed_at"], "quote_status": p["quote_status"]})
    names = dict(conn.execute("SELECT id, name FROM customers").fetchall())
    records = customer_records(conn)
    customers = sorted(({"customer_id": cid, "customer_name": names.get(cid, cid), **rec} for cid, rec in records.items()),
                       key=lambda c: (-c["requests"], c["customer_name"]))
    recent = [_row(r) | {"customer_name": names.get(r["customer_id"], r["customer_id"])} for r in conn.execute(
        "SELECT * FROM quote_outcomes ORDER BY outcome_date DESC, id DESC LIMIT 200")]
    return {
        "as_of": AS_OF.isoformat(),
        "all": _tally(rows),
        "console": _tally([r for r in rows if r["source"] == "console"]),
        "history": _tally([r for r in rows if r["source"] == "history"]),
        "awaiting": awaiting,
        "customers": customers,
        "recent": recent,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="What customers did after price increases went out.")
    ap.add_argument("--db", help="database path (default: the demo database)")
    args = ap.parse_args()
    conn = db.connect(args.db)
    s = summary(conn)
    for label, t in (("Since Margin Guard", s["console"]), ("Before (history)", s["history"]), ("All", s["all"])):
        kept = f"{t['kept']:.0%}" if t["kept"] is not None else "n/a"
        print(f"{label:<20} {t['requests']:>3} increases: {t['accepted']} accepted, {t['negotiated']} negotiated, "
              f"{t['lost']} lost | recovered ${t['recovered_usd']:,.2f} of ${t['asked_kept_jobs_usd']:,.2f} asked on jobs kept"
              f" ({kept}) | "
              f"lost revenue ${t['lost_revenue_usd']:,.2f}")
    print(f"Waiting for the customer: {len(s['awaiting'])}")
    for c in s["customers"][:10]:
        print(f"  {c['customer_name']:<34} {c['requests']} increases: {c['accepted']}/{c['negotiated']}/{c['lost']}"
              f" (accepted/negotiated/lost), {c['pattern']}")


if __name__ == "__main__":
    main()
