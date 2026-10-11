"""Append-only event log. The coordinator (Day 2) consumes pending events by type."""

import json
import sqlite3

from .parser import EventDraft


def append(conn: sqlite3.Connection, draft: EventDraft, source_ref: str) -> int | None:
    """Insert an event. Returns its id, or None if an event with the same
    idempotency key already exists (a re-sent, forwarded, or already-applied change)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO events (event_type, idempotency_key, source_ref, payload) VALUES (?, ?, ?, ?)",
        (draft.event_type, draft.idempotency_key, source_ref, json.dumps(draft.payload)),
    )
    return cur.lastrowid if cur.rowcount else None


def pending(conn: sqlite3.Connection, event_type: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM events WHERE status = 'pending'"
    args: tuple = ()
    if event_type:
        sql += " AND event_type = ?"
        args = (event_type,)
    return conn.execute(sql + " ORDER BY id", args).fetchall()


def mark(conn: sqlite3.Connection, event_id: int, status: str) -> None:
    conn.execute("UPDATE events SET status = ? WHERE id = ?", (status, event_id))
