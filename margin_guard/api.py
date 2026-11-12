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

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import actions, attachments, backlog, catalog, coordinator, db, imports, ingest, leakage, outcomes, quotecheck
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
            "awaiting_reply": one("SELECT COUNT(*) FROM proposals p LEFT JOIN quote_outcomes o ON o.proposal_id = p.id"
                                  " WHERE p.kind = 'quote_action' AND p.status IN ('approved', 'edited')"
                                  " AND p.final_action IN ('reprice', 'contact_customer') AND o.id IS NULL"),
            "autonomy": _autonomy(c),
            # Data problems that make costing fail closed (no costing supplier, or more than one).
            "data_problems": catalog.costing_problems(c),
        }


AUTONOMY_PATH = ROOT / "evals" / "results" / "autonomy.json"


def _autonomy(c) -> dict | None:
    """Report only: how many open judgment calls clear the confidence bar the
    scenario eval found error-free. Nothing is ever approved automatically."""
    if not AUTONOMY_PATH.exists():
        return None
    bar = json.loads(AUTONOMY_PATH.read_text(encoding="utf-8"))
    if bar.get("threshold") is None:
        return {"threshold": None, "model": bar.get("model"), "would_clear": 0}
    would = c.execute(
        "SELECT COUNT(*) FROM proposals WHERE status = 'pending' AND kind = 'quote_action'"
        " AND decided_by = 'llm' AND confidence >= ?", (bar["threshold"],)).fetchone()[0]
    return {"threshold": bar["threshold"], "model": bar.get("model"), "would_clear": would,
            "eval_runs": bar.get("runs")}


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
        c = conn()
        rows = [_with_event(r) for r in c.execute(f"{_PROPOSAL_SELECT} WHERE {where} ORDER BY {order}", args)]
        # What the customer did, and how they've taken increases before: for people, not the model.
        done = outcomes.for_proposals(c, [r["id"] for r in rows]) if lane == "done" else {}
        records = outcomes.customer_records(c)
        for r in rows:
            if r["kind"] == "quote_action":
                r["outcome"] = done.get(r["id"])
                r["customer_record"] = records.get(r["facts"].get("customer_id"))
        return rows


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
        # Prices from a supplier the material isn't costed at: on file, no cards.
        alt: dict[str, list[str]] = {}
        for e in c.execute(
            """SELECT json_extract(payload, '$.email_id') AS email_id, json_extract(result, '$.note') AS note
               FROM events WHERE json_extract(result, '$.alt_supplier') = 1 ORDER BY id"""
        ):
            alt.setdefault(e["email_id"], []).append(e["note"])

        files: dict[str, list] = {}
        for a in c.execute("SELECT id, email_id, filename, content_type, note FROM email_attachments ORDER BY id"):
            files.setdefault(a["email_id"], []).append(
                {"id": a["id"], "filename": a["filename"], "content_type": a["content_type"], "note": a["note"]})

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
                "alt_supplier_notes": alt.get(r["id"], []),
                "attachments": files.get(r["id"], []),
            })
        return out


@app.get("/api/materials")
def materials() -> list[dict]:
    with _conn_lock:
        return [dict(r) for r in conn().execute("SELECT id, name, category, cost_per_lb FROM materials ORDER BY id")]


class QuoteLine(BaseModel):
    part_id: str
    qty: float
    unit_price: float


class QuoteCheckBody(BaseModel):
    customer_id: str
    valid_days: int
    margin_floor: float
    lines: list[QuoteLine]


@app.get("/api/parts")
def parts() -> list[dict]:
    with _conn_lock:
        return quotecheck.parts_catalog(conn())


@app.post("/api/quote-check")
def quote_check(b: QuoteCheckBody) -> dict:
    """Will a price change already on file land inside this quote? Reads only; saves nothing."""
    with _conn_lock:
        try:
            return quotecheck.check(conn(), customer_id=b.customer_id, valid_days=b.valid_days,
                                    margin_floor=b.margin_floor, lines=[ln.model_dump() for ln in b.lines])
        except quotecheck.CheckError as exc:
            raise HTTPException(400, str(exc)) from exc


class StageBody(BaseModel):
    filename: str
    text: str


class ImportPlanBody(BaseModel):
    mapping: dict[str, str | None]
    suppliers: dict[str, str] = {}
    matches: dict[str, str] = {}        # "vendor_id|item" -> material id, or "" for "not an item we stock"
    remember: bool = False


DEMO_IMPORTS = {"invoices_ap_export.csv", "invoices_demo.csv"}


def _imp(fn, *args, **kwargs):
    with _conn_lock:
        try:
            return fn(conn(), *args, **kwargs)
        except imports.ImportError_ as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/imports")
def import_history() -> list[dict]:
    return _imp(imports.history)


@app.get("/api/imports/demo/{name}")
def demo_import_file(name: str) -> dict:
    """Sample files for trying the import without one of your own."""
    if name not in DEMO_IMPORTS:
        raise HTTPException(404, f"no demo file {name!r}")
    return {"filename": name, "text": (ROOT / "data" / name).read_text(encoding="utf-8")}


@app.get("/api/vendors")
def vendors() -> list[dict]:
    with _conn_lock:
        return [dict(r) for r in conn().execute("SELECT id, name FROM vendors ORDER BY name")]


@app.post("/api/imports/invoices")
def stage_invoices(b: StageBody) -> dict:
    """Store an uploaded invoice export as-is and suggest a column for each field. Writes nothing else."""
    return _imp(imports.stage, b.filename, b.text)


@app.post("/api/imports/{import_id}/preview")
def preview_import(import_id: int, b: ImportPlanBody) -> dict:
    """Validate, match and dry-run the import; nothing is kept."""
    return _imp(imports.preview, import_id, b.mapping, b.suppliers, b.matches)


@app.post("/api/imports/{import_id}/commit")
def commit_import(import_id: int, b: ImportPlanBody) -> dict:
    """Write the import in one transaction, then put any drift cards in front of a person."""
    _require_idle()
    result = _imp(imports.commit, import_id, b.mapping, b.suppliers, b.matches, b.remember)
    bus.publish("import.committed", {"import_id": import_id})
    _run_job(f"import {import_id}", _coordinate)
    return result


@app.post("/api/imports/{import_id}/discard")
def discard_import(import_id: int) -> dict:
    _imp(imports.discard, import_id)
    return {"import_id": import_id, "status": "discarded"}


class OutcomeBody(BaseModel):
    outcome: str
    recovered_usd: str | float | None = None
    on: str | None = None
    note: str | None = None


def _out(fn, *args, **kwargs):
    with _conn_lock:
        try:
            return fn(conn(), *args, **kwargs)
        except outcomes.OutcomeError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/outcomes")
def outcomes_summary() -> dict:
    """What customers did after increases went out: recovered of asked, lost, waiting, by customer."""
    return _out(outcomes.summary)


@app.post("/api/proposals/{proposal_id}/outcome")
def record_outcome(proposal_id: int, b: OutcomeBody) -> dict:
    result = _out(outcomes.record, proposal_id, b.outcome, recovered_usd=b.recovered_usd, on=b.on, note=b.note)
    bus.publish("outcome.recorded", {"proposal_id": proposal_id, "outcome": b.outcome})
    return result


@app.post("/api/outcomes/{outcome_id}/undo")
def undo_outcome(outcome_id: int) -> dict:
    _out(outcomes.undo, outcome_id)
    bus.publish("outcome.recorded", {"outcome_id": outcome_id, "outcome": None})
    return {"outcome_id": outcome_id, "undone": True}


def _bl(fn, *args):
    with _conn_lock:
        try:
            return fn(conn(), *args)
        except backlog.BacklogError as exc:
            raise HTTPException(400, str(exc)) from exc


@app.get("/api/backlog")
def backlog_report() -> dict:
    """Won orders whose material isn't bought yet: increases they'll absorb, what buying now saves."""
    return _bl(backlog.analyze)


@app.post("/api/backlog/{quote_id}/buy-now")
def backlog_buy_now(quote_id: str) -> dict:
    result = _bl(backlog.buy_now, quote_id)
    bus.publish("backlog.changed", result)
    return result


@app.post("/api/backlog/{quote_id}/undo-buy")
def backlog_undo_buy(quote_id: str) -> dict:
    result = _bl(backlog.undo_buy, quote_id)
    bus.publish("backlog.changed", result)
    return result


@app.get("/api/leakage")
def leakage_report() -> dict:
    """Margin leaked on won jobs because costs moved between quote and order."""
    with _conn_lock:
        return leakage.analyze(conn())


@app.get("/api/attachments/{attachment_id}")
def attachment(attachment_id: int) -> Response:
    """The original file a supplier sent, so any extracted price can be checked against it."""
    with _conn_lock:
        row = conn().execute("SELECT filename, content_type, data FROM email_attachments WHERE id = ?",
                             (attachment_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"attachment {attachment_id} not found")
    return Response(row["data"], media_type=row["content_type"],
                    headers={"Content-Disposition": f'inline; filename="{row["filename"]}"'})


@app.get("/api/outbox")
def outbox() -> list[dict]:
    with _conn_lock:
        return [dict(r) for r in conn().execute("SELECT * FROM outbox ORDER BY id DESC")]


@app.get("/api/demo-emails")
def demo_emails() -> list[dict]:
    return json.loads(DEMO_EMAILS_PATH.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ data (read-only)


@app.get("/api/data/quotes")
def data_quotes() -> list[dict]:
    """Every quote with its value and margin at current prices and quote-time costs."""
    with _conn_lock:
        return [dict(r) for r in conn().execute(
            """SELECT q.id, q.customer_id, c.name AS customer_name, c.tier, q.status, q.issued_date, q.valid_until,
                      q.margin_floor,
                      ROUND(SUM(ql.qty * ql.unit_price), 2) AS value_usd,
                      ROUND(1 - SUM(ql.qty * (ql.material_cost_basis + ql.conversion_cost))
                                / SUM(ql.qty * ql.unit_price), 4) AS margin,
                      COUNT(ql.id) AS lines,
                      (SELECT COUNT(*) FROM quote_revisions r WHERE r.quote_id = q.id) AS revisions,
                      (SELECT COUNT(*) FROM proposals p WHERE p.quote_id = q.id AND p.status = 'pending') AS open_cards
               FROM quotes q
               JOIN customers c ON c.id = q.customer_id
               JOIN quote_lines ql ON ql.quote_id = q.id
               GROUP BY q.id
               ORDER BY q.status = 'open' DESC, q.id DESC"""
        )]


@app.get("/api/data/quotes/{quote_id}")
def data_quote(quote_id: str) -> dict:
    """One quote in full: lines, every price revision, and every card ever raised on it."""
    with _conn_lock:
        c = conn()
        q = c.execute(
            """SELECT q.*, c.name AS customer_name, c.tier, c.price_lock_until, c.contract_note,
                      c.buyer_name, c.buyer_phone, c.buyer_email, c.account_manager, c.account_manager_phone
               FROM quotes q JOIN customers c ON c.id = q.customer_id WHERE q.id = ?""",
            (quote_id,),
        ).fetchone()
        if q is None:
            raise HTTPException(404, f"no quote {quote_id}")
        lines = c.execute(
            """SELECT ql.id, ql.part_id, p.name AS part_name, ql.qty, ql.unit_price, ql.material_cost_basis,
                      ql.conversion_cost,
                      (SELECT GROUP_CONCAT(m.name, ' + ') FROM part_materials pm JOIN materials m ON m.id = pm.material_id
                       WHERE pm.part_id = ql.part_id) AS materials
               FROM quote_lines ql JOIN parts p ON p.id = ql.part_id WHERE ql.quote_id = ? ORDER BY ql.id""",
            (quote_id,),
        ).fetchall()
        revisions = c.execute(
            """SELECT r.*, p.name AS part_name FROM quote_revisions r
               JOIN quote_lines ql ON ql.id = r.line_id JOIN parts p ON p.id = ql.part_id
               WHERE r.quote_id = ? ORDER BY r.id""",
            (quote_id,),
        ).fetchall()
        cards = c.execute(
            """SELECT p.id, p.action, p.final_action, p.status, p.decided_by, p.exposure_usd, p.created_at,
                      json_extract(e.payload, '$.material_id') AS material_id,
                      json_extract(e.payload, '$.email_id') AS email_id
               FROM proposals p JOIN events e ON e.id = p.event_id WHERE p.quote_id = ? ORDER BY p.id""",
            (quote_id,),
        ).fetchall()
        return {**dict(q), "lines": [dict(r) for r in lines], "revisions": [dict(r) for r in revisions],
                "cards": [dict(r) for r in cards]}


@app.get("/api/data/customers")
def data_customers() -> list[dict]:
    with _conn_lock:
        return [dict(r) for r in conn().execute(
            """SELECT c.*,
                      (SELECT COUNT(*) FROM quotes q WHERE q.customer_id = c.id AND q.status = 'open') AS open_quotes,
                      (SELECT ROUND(COALESCE(SUM(ql.qty * ql.unit_price), 0), 2) FROM quotes q
                       JOIN quote_lines ql ON ql.quote_id = q.id
                       WHERE q.customer_id = c.id AND q.status = 'open') AS open_value_usd,
                      (SELECT COUNT(*) FROM quotes q WHERE q.customer_id = c.id AND q.status = 'won') AS won_quotes
               FROM customers c ORDER BY c.name"""
        )]


@app.get("/api/data/materials")
def data_materials() -> list[dict]:
    """Each material: cost today, its full price history including scheduled changes,
    where each change came from, and which parts use it."""
    with _conn_lock:
        c = conn()
        out = []
        for m in c.execute("SELECT * FROM materials ORDER BY id").fetchall():
            history = c.execute(
                """SELECT h.cost_per_lb, h.effective_date, v.name AS vendor_name,
                          json_extract(e.payload, '$.email_id') AS email_id
                   FROM material_price_history h
                   LEFT JOIN vendors v ON v.id = h.vendor_id
                   LEFT JOIN events e ON e.id = h.source_event_id
                   WHERE h.material_id = ? ORDER BY h.effective_date, h.id""",
                (m["id"],),
            ).fetchall()
            parts = c.execute(
                """SELECT p.name FROM part_materials pm JOIN parts p ON p.id = pm.part_id
                   WHERE pm.material_id = ? ORDER BY p.id""",
                (m["id"],),
            ).fetchall()
            out.append({**dict(m), "aliases": json.loads(m["aliases"]),
                        "history": [dict(h) for h in history], "parts": [p["name"] for p in parts]})
        return out


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


@app.post("/api/proposals/{proposal_id}/redecide")
def redecide(proposal_id: int) -> dict:
    """Re-decide an approved quote with corrected numbers (the original decision stands)."""
    _require_idle()
    event_id = _act(actions.redecide_correction, proposal_id)
    bus.publish("proposal.reviewed", {"id": proposal_id, "status": "approved"})
    _run_job("redecide", _coordinate)
    return {"event_id": event_id}


@app.post("/api/inbox")
def receive_email(b: NewEmail) -> dict:
    if b.demo_id:
        demo = next((d for d in demo_emails() if d["id"] == b.demo_id), None)
        if demo is None:
            raise HTTPException(404, f"no demo email {b.demo_id!r}")
        from_addr, subject, body = demo["from"], demo["subject"], demo["body"]
        demo_files = [DEMO_EMAILS_PATH.parent / rel for rel in demo.get("attachments", [])]
    elif b.from_addr and b.subject and b.body:
        from_addr, subject, body = b.from_addr, b.subject, b.body
        demo_files = []
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
        for f in demo_files:
            attachments.add(c, email_id, f.name, f.read_bytes())
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
