"""HTTP API for the approval console.

    uvicorn margin_guard.api:app --port 8000

Reads and reviewer actions run on one shared connection (serialized by a lock).
Slow work (reading a new email, running the coordinator, which calls Claude)
runs on a background thread with its own connection and reports progress over
SSE at /api/stream. With SQLite in WAL mode the console stays responsive meanwhile.
"""

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import actions, coordinator, db, ingest
from .config import AS_OF, DB_PATH, MODEL, ROOT

DEMO_EMAILS_PATH = ROOT / "data" / "demo_emails.json"


# ------------------------------------------------------------------ live bus


class Bus:
    """Fan-out of progress messages from worker threads to SSE clients."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[asyncio.Queue] = set()

    def publish(self, kind: str, data: dict) -> None:
        if self.loop is None:
            return
        msg = {"event": kind, "data": json.dumps(data)}
        for q in list(self.clients):
            self.loop.call_soon_threadsafe(q.put_nowait, msg)


bus = Bus()
_conn = None
_conn_lock = threading.Lock()
_job_lock = threading.Lock()


def conn():
    global _conn
    if _conn is None:
        _conn = db.connect(DB_PATH)
    return _conn


@asynccontextmanager
async def lifespan(_app: FastAPI):
    bus.loop = asyncio.get_running_loop()
    yield


app = FastAPI(title="Margin Guard", lifespan=lifespan)


def _require_idle() -> None:
    if _job_lock.locked():
        raise HTTPException(409, "the agents are already working; try again in a moment")


def _run_job(name: str, work) -> None:
    """Run slow work on a background thread, one job at a time."""
    if not _job_lock.acquire(blocking=False):
        raise HTTPException(409, "the agents are already working; try again in a moment")

    def target():
        job_conn = db.connect(DB_PATH)
        try:
            bus.publish("job.started", {"job": name})
            work(job_conn)
            bus.publish("job.finished", {"job": name})
        except Exception as exc:  # surface failures in the feed rather than dying silently
            bus.publish("job.failed", {"job": name, "error": f"{type(exc).__name__}: {exc}"})
        finally:
            job_conn.close()
            _job_lock.release()

    threading.Thread(target=target, daemon=True).start()


def _coordinate(job_conn) -> None:
    coordinator.run(job_conn, notify=bus.publish)


# ------------------------------------------------------------------ reads


def _proposal_row(r) -> dict:
    d = dict(r)
    d["facts"] = json.loads(d["facts"])
    return d


_PROPOSAL_SELECT = """
    SELECT p.*, e.payload AS event_payload, ie.subject AS email_subject, v.name AS vendor_name
    FROM proposals p
    JOIN events e ON e.id = p.event_id
    LEFT JOIN inbox_emails ie ON ie.id = json_extract(e.payload, '$.email_id')
    LEFT JOIN vendors v ON v.id = json_extract(e.payload, '$.vendor_id')
"""


def _with_event(r) -> dict:
    d = _proposal_row(r)
    payload = json.loads(d.pop("event_payload"))
    d["event"] = {
        "material_id": payload.get("material_id"),
        "effective_date": payload.get("effective_date"),
        "pct_change": payload.get("pct_change"),
        "email_subject": d.pop("email_subject"),
        "vendor_name": d.pop("vendor_name"),
    }
    return d


@app.get("/api/overview")
def overview() -> dict:
    with _conn_lock:
        c = conn()
        one = lambda sql: c.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "as_of": AS_OF.isoformat(),
            "model": MODEL,
            "agents_busy": _job_lock.locked(),
            "needs_you": one("SELECT COUNT(*) FROM proposals WHERE status = 'pending'"
                             " AND (decided_by <> 'rule' OR kind = 'event_review')"),
            "needs_you_exposure": one("SELECT COALESCE(SUM(exposure_usd), 0) FROM proposals WHERE status = 'pending'"
                                      " AND decided_by <> 'rule' AND kind = 'quote_action'"),
            "rule_pending": one("SELECT COUNT(*) FROM proposals WHERE status = 'pending'"
                                " AND decided_by = 'rule' AND kind = 'quote_action'"),
            "live_exposure": one("SELECT COALESCE(SUM(exposure_usd), 0) FROM proposals"
                                 " WHERE status = 'pending' AND kind = 'quote_action'"),
            "done": one("SELECT COUNT(*) FROM proposals WHERE status IN ('approved', 'edited', 'rejected')"),
            "outbox": one("SELECT COUNT(*) FROM outbox"),
        }


_LANES = {
    "decide": "p.status = 'pending' AND (p.decided_by <> 'rule' OR p.kind = 'event_review')",
    "rules": "p.status = 'pending' AND p.decided_by = 'rule' AND p.kind = 'quote_action'",
    "done": "p.status IN ('approved', 'edited', 'rejected')",
}


@app.get("/api/queue")
def queue(lane: str = "decide", email: str | None = None) -> list[dict]:
    """Cards in one lane, optionally only those that came from one supplier email."""
    where = _LANES.get(lane)
    if where is None:
        raise HTTPException(400, f"unknown lane {lane!r}")
    args: tuple = ()
    if email:
        where += " AND json_extract(e.payload, '$.email_id') = ?"
        args = (email,)
    order = "p.reviewed_at DESC LIMIT 300" if lane == "done" else "p.kind DESC, p.exposure_usd DESC, p.id"
    with _conn_lock:
        rows = conn().execute(f"{_PROPOSAL_SELECT} WHERE {where} ORDER BY {order}", args).fetchall()
        return [_with_event(r) for r in rows]


@app.get("/api/inbox")
def inbox() -> list[dict]:
    """Each email with its current state: where its review stands, and what it led to."""
    with _conn_lock:
        c = conn()
        rows = c.execute(
            """SELECT ie.id, ie.from_addr, ie.subject, ie.body, ie.received_at, ie.status, ie.outcome, ie.note,
                      ie.error, v.name AS vendor_name
               FROM inbox_emails ie
               LEFT JOIN vendors v ON v.email_domain = lower(substr(ie.from_addr, instr(ie.from_addr, '@') + 1))
               ORDER BY ie.received_at DESC"""
        ).fetchall()
        # Every card that traces back to each email (including price changes a person
        # created by resolving a review, which keep the email_id).
        cards: dict[str, list] = {}
        for p in c.execute(
            """SELECT json_extract(e.payload, '$.email_id') AS email_id, p.kind, p.status, p.decided_by,
                      p.quote_id, p.reviewer_note
               FROM proposals p JOIN events e ON e.id = p.event_id"""
        ):
            cards.setdefault(p["email_id"], []).append(p)

        out = []
        for r in rows:
            mine = cards.get(r["id"], [])
            quotes = [p for p in mine if p["kind"] == "quote_action"]
            review = next((p for p in mine if p["kind"] == "event_review"), None)
            out.append({
                **dict(r),
                "review_status": review["status"] if review else None,
                "review_note": review["reviewer_note"] if review else None,
                "quotes_checked": len({p["quote_id"] for p in quotes}),
                "needs_you": sum(1 for p in quotes if p["status"] == "pending" and p["decided_by"] != "rule"),
                "rule_pending": sum(1 for p in quotes if p["status"] == "pending" and p["decided_by"] == "rule"),
            })
        return out


@app.get("/api/materials")
def materials() -> list[dict]:
    with _conn_lock:
        return [dict(r) for r in conn().execute("SELECT id, name, cost_per_lb FROM materials ORDER BY id")]


@app.get("/api/outbox")
def outbox() -> list[dict]:
    with _conn_lock:
        return [dict(r) for r in conn().execute("SELECT * FROM outbox ORDER BY id DESC")]


@app.get("/api/demo-emails")
def demo_emails() -> list[dict]:
    return json.loads(DEMO_EMAILS_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ actions


class ReviewBody(BaseModel):
    verdict: str                       # approve | edit | reject
    action: str | None = None
    subject: str | None = None
    body: str | None = None
    note: str | None = None


class ResolveBody(BaseModel):
    material_id: str
    note: str | None = None


class NoteBody(BaseModel):
    note: str | None = None


class NewEmail(BaseModel):
    demo_id: str | None = None
    from_addr: str | None = None
    subject: str | None = None
    body: str | None = None


def _act(fn, *args, **kwargs):
    with _conn_lock:
        try:
            return fn(conn(), *args, **kwargs)
        except actions.ActionError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.post("/api/proposals/{proposal_id}/review")
def review(proposal_id: int, b: ReviewBody) -> dict:
    result = _act(actions.review, proposal_id, b.verdict, action=b.action, subject=b.subject, body=b.body, note=b.note)
    bus.publish("proposal.reviewed", {"id": proposal_id, "status": result["status"]})
    return result


@app.post("/api/proposals/{proposal_id}/reopen")
def reopen(proposal_id: int) -> dict:
    result = _act(actions.reopen, proposal_id)
    bus.publish("proposal.reviewed", {"id": proposal_id, "status": "pending"})
    return result


@app.post("/api/events/{event_id}/confirm-rules")
def confirm_rules(event_id: int) -> dict:
    n = _act(actions.confirm_rules, event_id)
    bus.publish("rules.confirmed", {"event_id": event_id, "count": n})
    return {"confirmed": n}


@app.post("/api/proposals/{proposal_id}/dismiss")
def dismiss(proposal_id: int, b: NoteBody) -> dict:
    result = _act(actions.dismiss_review, proposal_id, b.note)
    bus.publish("proposal.reviewed", {"id": proposal_id, "status": result["status"]})
    return result


@app.post("/api/proposals/{proposal_id}/resolve")
def resolve(proposal_id: int, b: ResolveBody) -> dict:
    _require_idle()
    event_id = _act(actions.resolve_review, proposal_id, b.material_id, b.note)
    bus.publish("proposal.reviewed", {"id": proposal_id, "status": "approved"})
    _run_job("resolve", _coordinate)
    return {"event_id": event_id}


@app.post("/api/inbox")
def receive_email(b: NewEmail) -> dict:
    if b.demo_id:
        demo = next((d for d in demo_emails() if d["id"] == b.demo_id), None)
        if demo is None:
            raise HTTPException(404, f"no demo email {b.demo_id!r}")
        from_addr, subject, body = demo["from"], demo["subject"], demo["body"]
    elif b.from_addr and b.subject and b.body:
        from_addr, subject, body = b.from_addr, b.subject, b.body
    else:
        raise HTTPException(400, "send demo_id, or from_addr + subject + body")
    _require_idle()

    with _conn_lock:
        c = conn()
        n = c.execute("SELECT COUNT(*) FROM inbox_emails WHERE id LIKE 'N%'").fetchone()[0]
        email_id = f"N{n + 1:02d}"
        # The demo shop runs on a fixed calendar; new mail lands just after the latest.
        latest = c.execute("SELECT MAX(received_at) FROM inbox_emails").fetchone()[0]
        received = (datetime.fromisoformat(latest) + timedelta(minutes=5)).isoformat(timespec="seconds")
        c.execute(
            "INSERT INTO inbox_emails (id, from_addr, subject, body, received_at) VALUES (?, ?, ?, ?, ?)",
            (email_id, from_addr, subject, body, received),
        )
        c.commit()
    bus.publish("email.received", {"email_id": email_id, "from": from_addr, "subject": subject})

    def work(job_conn):
        bus.publish("email.reading", {"email_id": email_id})
        outcome = ingest.run(job_conn, email_id)[email_id]
        bus.publish("email.processed", {"email_id": email_id, "outcome": outcome})
        _coordinate(job_conn)

    _run_job(f"email {email_id}", work)
    return {"email_id": email_id}


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    bus.clients.add(q)

    async def gen():
        try:
            yield {"event": "hello", "data": json.dumps({"agents_busy": _job_lock.locked()})}
            while True:
                yield await q.get()
        finally:
            bus.clients.discard(q)

    return EventSourceResponse(gen(), ping=15)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "db": str(Path(DB_PATH))}
