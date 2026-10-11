"""Vendor email -> price-change events.

Two stages, kept separate on purpose:

1. extract()   - Claude reads the email and reports what it literally says
                 (material name, price, unit, pack size, % change, date).
2. normalize() - deterministic code turns that into catalog facts: resolves the
                 material, converts to $/lb, applies % changes to our own cost,
                 and runs sanity checks. Anything it can't stand behind is
                 routed to a person instead of guessed.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from . import catalog, llm
from .config import MIN_EXTRACTION_CONFIDENCE, SANITY_MAX_CHANGE
from .units import to_cost_per_lb

PriceUnit = Literal["lb", "kg", "cwt", "short_ton", "metric_ton"]


class ExtractedChange(BaseModel):
    material_text: str = Field(description="The material name exactly as the vendor wrote it.")
    new_price: float | None = Field(description="New price as written, before any unit conversion. Null if only a % change is given.")
    price_unit: PriceUnit | None = Field(description="Unit the new price is quoted in. 'cwt' = per hundredweight (100 lb).")
    pack_qty: float | None = Field(description="Pack size in price_unit when priced per pack, e.g. 25 for 'per 25 kg bag'. Null otherwise.")
    old_price: float | None = Field(description="Previous price if the email states it, in the same unit. Null otherwise.")
    pct_change: float | None = Field(description="Percent change if stated, e.g. 6.5 for +6.5%, -4 for a 4% decrease. Null otherwise.")
    effective_date: str | None = Field(description="Effective date as YYYY-MM-DD. Null if not stated.")


class EmailExtraction(BaseModel):
    email_kind: Literal["price_change", "price_advisory", "supplier_offer", "other"] = Field(
        description=(
            "price_change: a supplier announces a specific new price or % change for materials we buy. "
            "price_advisory: a heads-up with no exact price or no firm date. "
            "supplier_offer: a sales pitch or offer, not a change to an existing supply price. "
            "other: anything else (logistics, holidays, general news)."
        )
    )
    changes: list[ExtractedChange] = Field(
        description="One entry per material whose price is changing. Empty unless email_kind is price_change. "
        "Do not include materials mentioned only as unchanged."
    )
    confidence: float = Field(description="0-1 confidence that the extraction is complete and correct.")
    rationale: str = Field(description="One sentence on how the email was read.")


SYSTEM_PROMPT = """You read emails sent to the purchasing inbox of a custom rubber-molding manufacturer and extract supplier price changes.

Report only what the email states. Do not convert units, do not compute new prices from percentages, and do not guess a value that is not written; use null instead. Re-sent or forwarded notices are still price changes; extract them as written. A notice describing a change that has already taken effect is still a price_change."""


def extract(email: sqlite3.Row | dict) -> EmailExtraction:
    user = (
        f"From: {email['from_addr']}\n"
        f"Received: {email['received_at']}\n"
        f"Subject: {email['subject']}\n\n"
        f"{email['body']}"
    )
    return llm.parse(SYSTEM_PROMPT, user, EmailExtraction, effort="low")


# ---------------------------------------------------------------- normalize


@dataclass
class EventDraft:
    event_type: str                       # price_change.detected | price_change.needs_review
    idempotency_key: str
    payload: dict = field(default_factory=dict)


@dataclass
class Normalized:
    vendor_id: str | None
    ignored_reason: str | None = None
    drafts: list[EventDraft] = field(default_factory=list)


def price_change_key(material_id: str, cost_per_lb: float, effective: str) -> str:
    return f"price_change:{material_id}:{cost_per_lb:.4f}:{effective}"


def vendor_for_sender(conn: sqlite3.Connection, from_addr: str) -> str | None:
    domain = from_addr.rsplit("@", 1)[-1].strip().lower()
    row = conn.execute("SELECT id FROM vendors WHERE email_domain = ?", (domain,)).fetchone()
    return row["id"] if row else None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def normalize(conn: sqlite3.Connection, email: sqlite3.Row | dict, extraction: EmailExtraction) -> Normalized:
    vendor_id = vendor_for_sender(conn, email["from_addr"])
    result = Normalized(vendor_id=vendor_id)

    if extraction.email_kind in ("other", "supplier_offer"):
        result.ignored_reason = f"not a price change ({extraction.email_kind})"
        return result
    if extraction.email_kind == "price_change" and vendor_id is None:
        result.ignored_reason = "price notice from a sender who is not one of our suppliers"
        return result

    if extraction.email_kind == "price_advisory" or not extraction.changes:
        result.drafts.append(EventDraft(
            "price_change.needs_review",
            f"review:{email['id']}:0",
            {"email_id": email["id"], "vendor_id": vendor_id,
             "review_reasons": ["advisory without an exact price and effective date"],
             "summary": extraction.rationale},
        ))
        return result

    for i, ch in enumerate(extraction.changes):
        reasons: list[str] = []
        match = catalog.resolve_material(conn, ch.material_text, vendor_id)
        if match.material_id is None:
            detail = f" (candidates: {', '.join(match.candidates)})" if match.candidates else ""
            reasons.append(f"material '{ch.material_text}' is {match.method}{detail}")

        current = None
        if match.material_id:
            current = conn.execute(
                "SELECT cost_per_lb FROM materials WHERE id = ?", (match.material_id,)
            ).fetchone()["cost_per_lb"]

        new_cost = None
        if ch.new_price is not None and ch.price_unit is not None:
            new_cost = to_cost_per_lb(ch.new_price, ch.price_unit, ch.pack_qty)
        elif ch.pct_change is not None and current is not None:
            new_cost = current * (1 + ch.pct_change / 100)
        else:
            reasons.append("no usable price (needs a price with a unit, or a % change)")

        effective = _parse_date(ch.effective_date)
        if effective is None:
            reasons.append("no effective date")

        pct = None
        if new_cost is not None and current:
            pct = (new_cost - current) / current
            if abs(pct) > SANITY_MAX_CHANGE:
                reasons.append(f"{pct:+.1%} vs our cost exceeds the {SANITY_MAX_CHANGE:.0%} sanity bound; check units")

        if extraction.confidence < MIN_EXTRACTION_CONFIDENCE:
            reasons.append(f"low extraction confidence ({extraction.confidence:.2f})")

        payload = {
            "email_id": email["id"],
            "vendor_id": vendor_id,
            "material_text": ch.material_text,
            "material_id": match.material_id,
            "match_method": match.method,
            "old_cost_per_lb": current,
            "new_cost_per_lb": round(new_cost, 6) if new_cost is not None else None,
            "pct_change": round(pct, 6) if pct is not None else None,
            "effective_date": effective,
            "quoted": {"price": ch.new_price, "unit": ch.price_unit, "pack_qty": ch.pack_qty,
                       "pct_change": ch.pct_change, "old_price": ch.old_price},
            "extraction_confidence": extraction.confidence,
        }
        if reasons:
            payload["review_reasons"] = reasons
            result.drafts.append(EventDraft("price_change.needs_review", f"review:{email['id']}:{i}", payload))
        else:
            key = price_change_key(match.material_id, new_cost, effective)
            result.drafts.append(EventDraft("price_change.detected", key, payload))
    return result
