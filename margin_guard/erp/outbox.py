"""What an approval means for the ERP: writes queued in the same transaction as the approval.

Margin Guard writes to the ERP only what a person approved:

    reprice approved            quote_prices    the quotation's line prices, with a note on it
    call the customer approved  call_task       a Call activity for the account manager
    a price change acted on     supplier_price  a dated supplier price line; "acted on" means a
                                                person approved or confirmed a decision it
                                                raised, answered the question that created it,
                                                or applied an invoice drift

Each queued write carries what the ERP should hold before it (the old prices), so the writer
can refuse when someone changed the record in the ERP in the meantime. A price that came from
the ERP is never written back. Undoing a reprice cancels its queued write, or queues the
reverse if it was already sent.

Queueing happens only for a shop linked to an ERP (it has erp_links rows); a shop that has
never synced queues nothing. Sending is `python -m margin_guard.erp push` (odoo_writer.py).
"""

import json
import sqlite3

SYSTEM = "odoo"


def enabled(conn: sqlite3.Connection) -> bool:
    try:
        return bool(conn.execute("SELECT 1 FROM erp_links WHERE system = ? LIMIT 1", (SYSTEM,)).fetchone())
    except sqlite3.OperationalError:          # a database from before the connector
        return False


def _queue(conn, kind: str, key: str, payload: dict, proposal_id: int | None = None) -> int | None:
    cur = conn.execute("INSERT OR IGNORE INTO erp_outbox (system, kind, idempotency_key, payload, proposal_id) VALUES (?, ?, ?, ?, ?)",
                       (SYSTEM, kind, key, json.dumps(payload), proposal_id))
    return cur.lastrowid if cur.rowcount else None


def _price_change(conn, event_id: int) -> dict | None:
    e = conn.execute("SELECT event_type, source_ref, payload FROM events WHERE id = ?", (event_id,)).fetchone()
    if e is None or e["event_type"] != "price_change.detected":
        return None
    p = json.loads(e["payload"])
    if p.get("source") == SYSTEM or (e["source_ref"] or "").startswith(f"{SYSTEM}:"):
        return None                           # it came from the ERP; writing it back would echo
    if not (p.get("material_id") and p.get("vendor_id") and p.get("new_cost_per_lb") and p.get("effective_date")):
        return None
    return {"material_id": p["material_id"], "vendor_id": p["vendor_id"], "cost_per_lb": p["new_cost_per_lb"],
            "effective_date": p["effective_date"], "event_id": event_id}


def supplier_price(conn: sqlite3.Connection, event_id: int) -> None:
    """A person acted on this price change: put the price in the ERP."""
    if enabled(conn) and (p := _price_change(conn, event_id)):
        _queue(conn, "supplier_price", f"supplier_price:{event_id}", p)


def approved(conn: sqlite3.Connection, proposal: sqlite3.Row, action: str, subject: str | None, body: str | None) -> None:
    """A quote decision was approved: queue what it means for the ERP."""
    if not enabled(conn):
        return
    supplier_price(conn, proposal["event_id"])
    facts = json.loads(proposal["facts"])
    if action == "reprice":
        material = conn.execute("SELECT name FROM materials WHERE id = ?", (facts.get("material_id"),)).fetchone()
        revs = conn.execute("SELECT id, line_id, old_price, new_price FROM quote_revisions WHERE proposal_id = ? ORDER BY id",
                            (proposal["id"],)).fetchall()
        lines = [{"line_id": r["line_id"], "old": r["old_price"], "new": r["new_price"]} for r in revs]
        if lines:
            # Keyed by this approval's revisions: approving again after an undo is a new write.
            _queue(conn, "quote_prices", f"quote_prices:{proposal['id']}:{revs[0]['id']}", {
                "quote_id": proposal["quote_id"], "lines": lines, "material_id": facts.get("material_id"),
                "note": f"Revised prices approved in Margin Guard after the {material['name'] if material else 'material'} cost change."},
                proposal["id"])
    elif action == "contact_customer":
        buyer = facts.get("buyer") or {}
        n = conn.execute("SELECT COUNT(*) FROM erp_outbox WHERE kind = 'call_task' AND proposal_id = ?", (proposal["id"],)).fetchone()[0]
        _queue(conn, "call_task", f"call_task:{proposal['id']}:{n + 1}", {
            "quote_id": proposal["quote_id"], "summary": subject or f"Call about quote {proposal['quote_id']}",
            "note": body or "", "buyer": buyer.get("name"), "phone": buyer.get("phone")}, proposal["id"])


def reopened(conn: sqlite3.Connection, proposal_id: int) -> None:
    """A decision was undone: cancel what hasn't been sent, reverse prices that have."""
    if not enabled(conn):
        return
    for row in conn.execute("SELECT * FROM erp_outbox WHERE proposal_id = ? AND kind IN ('quote_prices', 'call_task')",
                            (proposal_id,)).fetchall():
        if row["status"] in ("pending", "failed", "conflict"):
            conn.execute("UPDATE erp_outbox SET status = 'cancelled', detail = 'decision undone before it was written' WHERE id = ?",
                         (row["id"],))
        elif row["status"] == "sent" and row["kind"] == "quote_prices":
            p = json.loads(row["payload"])
            _queue(conn, "quote_prices", f"quote_prices:undo:{row['id']}", {
                "quote_id": p["quote_id"], "lines": [{"line_id": ln["line_id"], "old": ln["new"], "new": ln["old"]} for ln in p["lines"]],
                "note": "The revised prices were undone in Margin Guard; the quoted prices are restored.", "undoes": row["id"]},
                proposal_id)
        # A call activity already in the ERP stays: someone may have made the call.


def pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM erp_outbox WHERE status IN ('pending', 'failed') ORDER BY id").fetchall()


def summary(conn: sqlite3.Connection) -> dict:
    try:
        return dict(conn.execute("SELECT status, COUNT(*) FROM erp_outbox GROUP BY status").fetchall())
    except sqlite3.OperationalError:
        return {}
