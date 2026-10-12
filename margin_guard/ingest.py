"""Process the vendor inbox: extract each new email, normalize, write events.

    python -m margin_guard.ingest            # all new emails
    python -m margin_guard.ingest --email E07
"""

import argparse
import json
import sqlite3
from pathlib import Path

from . import db, events, parser
from .config import DB_PATH


def outcome_for(normalized: parser.Normalized, created: list[int | None]) -> str:
    if normalized.ignored_reason:
        return "ignored"
    if any(d.event_type == "price_change.needs_review" for d in normalized.drafts):
        return "needs_review"
    if any(created):
        return "detected"
    return "duplicate"


def process_email(conn: sqlite3.Connection, email: sqlite3.Row, extract=parser.extract) -> str:
    try:
        extraction = extract(email)
    except Exception as exc:  # keep going; the failure is recorded on the email
        conn.execute(
            "UPDATE inbox_emails SET status = 'error', error = ? WHERE id = ?",
            (f"{type(exc).__name__}: {exc}", email["id"]),
        )
        conn.commit()
        return "error"

    normalized = parser.normalize(conn, email, extraction)
    created = [events.append(conn, d, source_ref=f"email:{email['id']}") for d in normalized.drafts]
    outcome = outcome_for(normalized, created)
    conn.execute(
        "UPDATE inbox_emails SET status = 'processed', outcome = ?, extraction = ?, note = ?, error = NULL WHERE id = ?",
        (outcome, extraction.model_dump_json(), normalized.ignored_reason, email["id"]),
    )
    conn.commit()
    return outcome


def run(conn: sqlite3.Connection, email_id: str | None = None, extract=parser.extract) -> dict[str, str]:
    sql = "SELECT * FROM inbox_emails WHERE status = 'new'"
    args: tuple = ()
    if email_id:
        sql, args = "SELECT * FROM inbox_emails WHERE id = ?", (email_id,)
    results = {}
    for email in conn.execute(sql + " ORDER BY received_at", args).fetchall():
        results[email["id"]] = process_email(conn, email, extract)
        print(f"  {email['id']}  {results[email['id']]:<13} {email['subject']}")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", help="process one email by id (even if already processed)")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--replay", type=Path, metavar="EXTRACTIONS_JSON",
                    help="reuse cached Claude extractions (e.g. evals/results/extractions.json); "
                         "emails not in the cache still go to Claude")
    args = ap.parse_args()
    conn = db.connect(args.db)

    extract = parser.extract
    if args.replay:
        cache = json.loads(args.replay.read_text(encoding="utf-8"))

        def extract(email):
            if email["id"] in cache:
                return parser.EmailExtraction.model_validate(cache[email["id"]])
            return parser.extract(email)

    run(conn, args.email, extract)
    print()
    for row in conn.execute("SELECT event_type, COUNT(*) n FROM events WHERE status = 'pending' GROUP BY event_type"):
        print(f"  pending {row['event_type']}: {row['n']}")


if __name__ == "__main__":
    main()
