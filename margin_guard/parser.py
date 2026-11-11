"""Vendor email -> price-change events.

Two stages, kept separate on purpose:

1. extract()   - Claude reads the email and reports what it literally says
                 (material name, price, unit, pack size, % change, date).
2. normalize() - deterministic code turns that into catalog facts: resolves the
                 material, converts to $/lb, applies % changes to the sending
                 supplier's own price,
                 and runs sanity checks. Anything it can't stand behind is
                 routed to a person instead of guessed.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from . import catalog, impact, llm, money
from .config import AS_OF, MIN_EXTRACTION_CONFIDENCE, SANITY_MAX_CHANGE
from .money import D

UNCHANGED = D("0.001")   # a price-list row within 0.1% of our cost is unchanged
from .units import to_cost_per_lb

PriceUnit = Literal["lb", "kg", "cwt", "short_ton", "metric_ton"]


class ExtractedChange(BaseModel):
    material_text: str = Field(description="The material name exactly as the vendor wrote it.")
    new_price: float | None = Field(description="New price as written, before any unit conversion. Null if only a % change is given.")
    price_unit: PriceUnit | None = Field(description="Unit the new price is quoted in. 'cwt' = per hundredweight (100 lb).")
    # Defaults keep extractions cached before these fields existed valid.
    price_in_cents: bool = Field(default=False, description=(
        "True when the price is written in cents, e.g. '118 cents per pound' or '118¢/lb'. "
        "new_price and old_price are then the number of cents as written."))
    currency: str = Field(default="USD", description=(
        "ISO 4217 code of the currency the price is written in, e.g. USD, CAD, EUR. "
        "USD when the email gives no other currency."))
    pack_qty: float | None = Field(description="Pack size in price_unit when priced per pack, e.g. 25 for 'per 25 kg bag'. Null otherwise.")
    old_price: float | None = Field(description="Previous price if the email states it, in the same unit. Null otherwise.")
    pct_change: float | None = Field(description="Percent change if stated, e.g. 6.5 for +6.5%, -4 for a 4% decrease. Null otherwise.")
    effective_date: str | None = Field(description="Effective date as YYYY-MM-DD. Null if not stated.")
    # Default keeps extractions cached before attachments existed valid.
    source: Literal["email", "attachment"] = Field(default="email", description=(
        "Where this price is written: 'email' for the email text, 'attachment' for an attached price list or letter."))


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

Report only what the email states. Do not convert units or currencies, do not compute new prices from percentages, and do not guess a value that is not written; use null instead. A price written in cents is reported as the number of cents with price_in_cents set. Re-sent or forwarded notices are still price changes; extract them as written. A notice describing a change that has already taken effect is still a price_change.

Attachments (price lists, price letters) are part of the email and appear after it as text. Extract the changes they state and set source to attachment. A price list usually lists many items: include only rows whose price is changing (a new price that differs from the current one, or a stated % change), and leave out rows whose price stays the same. Include rows for every material on the list; do not decide which ones this manufacturer buys. If an attachment could not be read, say so in the rationale and do not guess its contents."""


def _get(email: sqlite3.Row | dict, key: str, default=None):
    return email[key] if key in email.keys() else default


def extract(email: sqlite3.Row | dict) -> EmailExtraction:
    """`email` may carry `attachments_text` (see attachments.for_prompt), added by ingest."""
    user = (
        f"From: {email['from_addr']}\n"
        f"Received: {email['received_at']}\n"
        f"Subject: {email['subject']}\n\n"
        f"{email['body']}"
    )
    if _get(email, "attachments_text"):
        user += "\n\n" + email["attachments_text"]
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
    # Price-sheet rows left out on purpose (materials we don't buy from this supplier).
    skipped: list[str] = field(default_factory=list)


def price_change_key(vendor_id: str | None, material_id: str, cost_per_lb: float, effective: str) -> str:
    """Two suppliers announcing the same price on the same date are two changes."""
    return f"price_change:{vendor_id or '-'}:{material_id}:{cost_per_lb:.4f}:{effective}"


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

    unreadable = _get(email, "unreadable_attachments") or []
    # A supplier sent a file nobody could read. The model can't tell what's in a
    # scan, so its "not a price change" verdict is a guess; a person looks instead.
    if unreadable and vendor_id and not extraction.changes:
        result.drafts.append(EventDraft(
            "price_change.needs_review",
            f"review:{email['id']}:0",
            {"email_id": email["id"], "vendor_id": vendor_id,
             "review_reasons": [f"attachment {name} could not be read: {why}" for name, why in unreadable],
             "summary": extraction.rationale},
        ))
        return result

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
             "review_reasons": ([f"attachment {name} could not be read: {why}" for name, why in unreadable]
                                or ["advisory without an exact price and effective date"]),
             "summary": extraction.rationale},
        ))
        return result

    for i, ch in enumerate(extraction.changes):
        reasons: list[str] = []
        match = catalog.resolve_material(conn, ch.material_text, vendor_id)
        # A supplier's price list covers everything they sell. A row for a material
        # we don't buy is not a question for a person; leave it out and say so.
        if ch.source == "attachment" and match.method == "none":
            result.skipped.append(f"{ch.material_text}: not a material we buy from this supplier")
            continue
        if match.material_id is None:
            detail = f" (candidates: {', '.join(match.candidates)})" if match.candidates else ""
            reasons.append(f"material '{ch.material_text}' is {match.method}{detail}")

        # `current` is what the new price is compared against: this supplier's own
        # price today. For the costing supplier that is our catalog cost. An
        # alternate supplier's price is on file only if they've quoted before;
        # otherwise we compare against our catalog cost but can't apply a % to it.
        current = None
        own_price_known = False
        if match.material_id:
            catalog_cost = conn.execute(
                "SELECT cost_per_lb FROM materials WHERE id = ?", (match.material_id,)
            ).fetchone()["cost_per_lb"]
            if impact.moves_costing(conn, {"material_id": match.material_id, "vendor_id": vendor_id}):
                current, own_price_known = catalog_cost, True
            else:
                own = impact.supplier_cost(conn, match.material_id, vendor_id, AS_OF.isoformat())
                current, own_price_known = (own, True) if own is not None else (catalog_cost, False)

        new_cost = None
        if ch.new_price is not None and ch.price_unit is not None:
            new_cost = to_cost_per_lb(ch.new_price, ch.price_unit, ch.pack_qty, in_cents=ch.price_in_cents)
        elif ch.pct_change is not None and current is not None and own_price_known:
            new_cost = money.cost(D(current) * (1 + D(ch.pct_change) / 100))
        elif ch.pct_change is not None and current is not None:
            reasons.append("% change from an alternate supplier with no price of theirs on file")
        else:
            reasons.append("no usable price (needs a price with a unit, or a % change)")

        effective = _parse_date(ch.effective_date)
        if effective is None:
            reasons.append("no effective date")

        currency = (ch.currency or "USD").strip().upper()
        if currency != "USD" and ch.new_price is not None:
            reasons.append(f"priced in {currency}; costs are kept in USD, so it needs a converted price")

        pct = None
        if new_cost is not None and current:
            pct = money.pct((new_cost - D(current)) / D(current))
            if abs(pct) > D(SANITY_MAX_CHANGE):
                reasons.append(f"{pct:+.1%} vs our cost exceeds the {SANITY_MAX_CHANGE:.0%} sanity bound; check units")

        # A list priced in kg or per ton rounds; under 0.1% is the same price restated.
        if ch.source == "attachment" and pct is not None and abs(pct) < UNCHANGED and not reasons:
            result.skipped.append(f"{ch.material_text}: price unchanged")
            continue

        if extraction.confidence < MIN_EXTRACTION_CONFIDENCE:
            reasons.append(f"low extraction confidence ({extraction.confidence:.2f})")

        payload = {
            "email_id": email["id"],
            "vendor_id": vendor_id,
            "material_text": ch.material_text,
            "material_id": match.material_id,
            "match_method": match.method,
            "match_candidates": match.candidates,
            "old_cost_per_lb": current,
            "new_cost_per_lb": money.out(new_cost) if new_cost is not None else None,
            "pct_change": money.out(pct) if pct is not None else None,
            "effective_date": effective,
            "quoted": {"price": ch.new_price, "unit": ch.price_unit, "pack_qty": ch.pack_qty,
                       "in_cents": ch.price_in_cents, "currency": currency,
                       "pct_change": ch.pct_change, "old_price": ch.old_price},
            "extraction_confidence": extraction.confidence,
        }
        if reasons:
            payload["review_reasons"] = reasons
            result.drafts.append(EventDraft("price_change.needs_review", f"review:{email['id']}:{i}", payload))
        else:
            key = price_change_key(vendor_id, match.material_id, new_cost, effective)
            result.drafts.append(EventDraft("price_change.detected", key, payload))
    if not result.drafts and result.skipped:
        result.ignored_reason = "price list has no changes to materials we buy from this supplier"
    return result
