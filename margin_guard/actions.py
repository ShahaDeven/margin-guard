"""What happens when a person acts on a card. Plain functions; the API is a thin layer over these.

    approve         sign off on the proposal as written
    edit            sign off with changes (a different action and/or a rewritten draft)
    reject          the proposal is wrong; nothing happens
    reopen          undo any of the above and put the card back in the queue
    confirm_rules   approve every pending rule decision for one price change
    resolve_review  answer a review item ("Black 70 means EPDM 70"), which creates the
                    price change the email should have produced in the first place

Approving a reprice writes the new unit prices to the quote; approving a reprice
or contact_customer puts the draft in the outbox. Every verdict is stored next to
the original proposal; that pair is the training signal for the eval loop.
"""

import json
import sqlite3

from . import events
from .parser import EventDraft, price_change_key

QUOTE_ACTIONS = {"honor", "absorb", "reprice", "contact_customer"}


class ActionError(ValueError):
    pass


def _pending(conn: sqlite3.Connection, proposal_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ActionError(f"proposal {proposal_id} not found")
    if row["status"] != "pending":
        raise ActionError(f"proposal {proposal_id} is already {row['status']}")
    return row


def _apply(conn: sqlite3.Connection, p: sqlite3.Row, action: str, subject: str | None, body: str | None) -> None:
    facts = json.loads(p["facts"])
    if action == "reprice":
        for ln in facts["lines"]:
            if ln["proposed_unit_price"] == ln["unit_price"]:
                continue
            old = conn.execute("SELECT unit_price FROM quote_lines WHERE id = ?", (ln["line_id"],)).fetchone()
            conn.execute("UPDATE quote_lines SET unit_price = ? WHERE id = ?", (ln["proposed_unit_price"], ln["line_id"]))
            conn.execute(
                "INSERT INTO quote_revisions (quote_id, line_id, proposal_id, old_price, new_price) VALUES (?, ?, ?, ?, ?)",
                (p["quote_id"], ln["line_id"], p["id"], old["unit_price"], ln["proposed_unit_price"]),
            )
    if action in ("reprice", "contact_customer"):
        buyer, am = facts.get("buyer") or {}, facts.get("account_manager") or {}
        if action == "reprice":
            kind = "customer_email"
            recipient = f"{buyer.get('name') or facts['customer_name']} <{buyer.get('email') or 'no email on file'}>"
        else:
            kind = "call_task"
            recipient = (f"{am.get('name') or 'Account manager'}: call {buyer.get('name') or facts['customer_name']}"
                         f" ({facts['customer_name']}) at {buyer.get('phone') or 'no phone on file'}")
        conn.execute(
            "INSERT INTO outbox (proposal_id, kind, recipient, subject, body) VALUES (?, ?, ?, ?, ?)",
            (p["id"], kind, recipient, subject or f"Quote {p['quote_id']}", body or ""),
        )


def review(conn: sqlite3.Connection, proposal_id: int, verdict: str, *, action: str | None = None,
           subject: str | None = None, body: str | None = None, note: str | None = None) -> dict:
    p = _pending(conn, proposal_id)
    if p["kind"] != "quote_action":
        raise ActionError("review items are handled with resolve_review or reject")

    if verdict == "reject":
        conn.execute(
            "UPDATE proposals SET status = 'rejected', reviewer_note = ?, reviewed_at = datetime('now') WHERE id = ?",
            (note, proposal_id),
        )
        conn.commit()
        return get(conn, proposal_id)

    if verdict not in ("approve", "edit"):
        raise ActionError(f"unknown verdict {verdict!r}")
    final_action = (action if verdict == "edit" and action else p["action"])
    if final_action not in QUOTE_ACTIONS:
        raise ActionError(f"choose an action ({', '.join(sorted(QUOTE_ACTIONS))}) before approving")
    final_subject = subject if verdict == "edit" and subject is not None else p["draft_subject"]
    final_body = body if verdict == "edit" and body is not None else p["draft_body"]
    if final_action in ("reprice", "contact_customer") and not (final_body or "").strip():
        raise ActionError(f"a {final_action} needs a draft before it can be approved")

    changed = (final_action, final_subject, final_body) != (p["action"], p["draft_subject"], p["draft_body"])
    _apply(conn, p, final_action, final_subject, final_body)
    conn.execute(
        """UPDATE proposals SET status = ?, final_action = ?, final_subject = ?, final_body = ?,
           reviewer_note = ?, reviewed_at = datetime('now') WHERE id = ?""",
        ("edited" if changed else "approved", final_action, final_subject, final_body, note, proposal_id),
    )
    conn.commit()
    return get(conn, proposal_id)


def reopen(conn: sqlite3.Connection, proposal_id: int) -> dict:
    """Undo a verdict: put the card back in the queue.

    Reverts any prices an approved reprice wrote and withdraws its outbox entry.
    Refuses if a later revision has changed the same quote line since, because
    blindly restoring the old price would clobber that newer decision.
    """
    p = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if p is None:
        raise ActionError(f"proposal {proposal_id} not found")
    if p["kind"] != "quote_action":
        raise ActionError("a resolved supplier email can't be reopened; its price change has already run")
    if p["status"] not in ("approved", "edited", "rejected"):
        raise ActionError(f"proposal {proposal_id} is {p['status']}, nothing to undo")

    revisions = conn.execute(
        "SELECT * FROM quote_revisions WHERE proposal_id = ? ORDER BY id DESC", (proposal_id,)).fetchall()
    for rev in revisions:
        current = conn.execute("SELECT unit_price FROM quote_lines WHERE id = ?", (rev["line_id"],)).fetchone()
        if abs(current["unit_price"] - rev["new_price"]) > 1e-9:
            raise ActionError(f"quote {p['quote_id']} has been revised again since; undo that decision first")
    for rev in revisions:
        conn.execute("UPDATE quote_lines SET unit_price = ? WHERE id = ?", (rev["old_price"], rev["line_id"]))
    conn.execute("DELETE FROM quote_revisions WHERE proposal_id = ?", (proposal_id,))
    conn.execute("DELETE FROM outbox WHERE proposal_id = ?", (proposal_id,))
    conn.execute(
        """UPDATE proposals SET status = 'pending', final_action = NULL, final_subject = NULL, final_body = NULL,
           reviewer_note = NULL, reviewed_at = NULL WHERE id = ?""",
        (proposal_id,),
    )
    conn.commit()
    return get(conn, proposal_id)


def confirm_rules(conn: sqlite3.Connection, event_id: int) -> int:
    """Approve every pending rule decision (honor/absorb) for one price change."""
    cur = conn.execute(
        """UPDATE proposals SET status = 'approved', final_action = action, reviewed_at = datetime('now')
           WHERE event_id = ? AND kind = 'quote_action' AND decided_by = 'rule' AND status = 'pending'""",
        (event_id,),
    )
    conn.commit()
    return cur.rowcount


def resolve_review(conn: sqlite3.Connection, proposal_id: int, material_id: str, note: str | None = None) -> int:
    """Turn a review item into the price change it describes. Returns the new event id.

    The caller then runs the coordinator to work out the impact.
    """
    p = _pending(conn, proposal_id)
    if p["kind"] != "event_review":
        raise ActionError("only review items can be resolved")
    payload = json.loads(p["facts"])
    if payload.get("new_cost_per_lb") is None or not payload.get("effective_date"):
        raise ActionError("this email has no exact price and date to apply; dismiss it instead")
    mat = conn.execute("SELECT name, cost_per_lb FROM materials WHERE id = ?", (material_id,)).fetchone()
    if mat is None:
        raise ActionError(f"unknown material {material_id}")

    new_cost = payload["new_cost_per_lb"]
    resolved = {
        **{k: v for k, v in payload.items() if k != "review_reasons"},
        "material_id": material_id,
        "match_method": "person",
        "old_cost_per_lb": mat["cost_per_lb"],
        "pct_change": round((new_cost - mat["cost_per_lb"]) / mat["cost_per_lb"], 6),
    }
    event_id = events.append(
        conn,
        EventDraft("price_change.detected", price_change_key(material_id, new_cost, payload["effective_date"]), resolved),
        source_ref=f"review:{proposal_id}",
    )
    if event_id is None:
        raise ActionError("that price change is already on file")
    conn.execute(
        """UPDATE proposals SET status = 'approved', final_action = 'resolve_event', reviewer_note = ?,
           reviewed_at = datetime('now') WHERE id = ?""",
        (note or f"Material confirmed as {mat['name']}", proposal_id),
    )
    conn.commit()
    return event_id


def dismiss_review(conn: sqlite3.Connection, proposal_id: int, note: str | None = None) -> dict:
    p = _pending(conn, proposal_id)
    if p["kind"] != "event_review":
        raise ActionError("only review items can be dismissed")
    conn.execute(
        "UPDATE proposals SET status = 'rejected', reviewer_note = ?, reviewed_at = datetime('now') WHERE id = ?",
        (note or "Dismissed", proposal_id),
    )
    conn.commit()
    return get(conn, proposal_id)


def get(conn: sqlite3.Connection, proposal_id: int) -> dict:
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    return {**dict(row), "facts": json.loads(row["facts"])}
