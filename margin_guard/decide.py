"""Decide what to do with one affected quote.

Rules settle the clear cases (expires first, price lock, margin still above the
floor). Claude handles only the judgment calls: below-floor quotes where the
right move depends on deal size, account tier and free-text contract notes.
It also drafts the email. Prices always come from impact.py, never from the model.
"""

import json
from typing import Callable, Literal

from pydantic import BaseModel, Field

from . import llm
from .config import ROOT

POLICY = (ROOT / "data" / "pricing_policy.md").read_text(encoding="utf-8")


class QuoteDecision(BaseModel):
    action: Literal["reprice", "contact_customer"] = Field(description="The action the policy calls for.")
    confidence: float = Field(description="0-1 confidence that this is the action the policy calls for.")
    rationale: str = Field(description="One or two sentences citing the facts and the policy clause that decided it.")
    email_subject: str
    email_body: str = Field(description="The draft described in the policy for this action. Plain text.")


SYSTEM_PROMPT = f"""You are the pricing assistant at a custom rubber-molding manufacturer. A supplier cost increase has pushed an open quote below its margin floor. Decide the action the company policy calls for and write the draft it describes.

{POLICY}

The facts are computed by the pricing system and are correct. Use the proposed_unit_price values exactly as given; never compute prices yourself."""


def llm_decide(facts: dict) -> QuoteDecision:
    return llm.parse(SYSTEM_PROMPT, json.dumps(facts, indent=2), QuoteDecision, effort="low")


Decider = Callable[[dict], QuoteDecision]


def rule_decision(facts: dict) -> tuple[str, str, str] | None:
    """(action, rule_id, rationale) when a rule settles it, else None."""
    if not facts["can_accept_after_change"]:
        return ("honor", "expires_before_change",
                f"Quote is valid until {facts['valid_until']}, before the change takes effect on "
                f"{facts['effective_date']}.")
    lock = facts["price_lock_until"]
    if lock and lock >= facts["effective_date"]:
        return ("honor", "price_lock",
                f"{facts['customer_name']} has prices locked through {lock}. "
                f"Unavoidable margin loss: ${facts['exposure_usd']:,.2f}.")
    if facts["margin_after"] >= facts["margin_floor"]:
        return ("absorb", "within_floor",
                f"Margin moves {facts['margin_before']:.1%} -> {facts['margin_after']:.1%}, "
                f"still at or above the {facts['margin_floor']:.1%} floor.")
    return None


def decide(facts: dict, decider: Decider = llm_decide) -> dict:
    proposal = {
        "kind": "quote_action",
        "quote_id": facts["quote_id"],
        "facts": facts,
        "exposure_usd": facts["exposure_usd"],
        "rule_id": None,
        "confidence": None,
        "draft_subject": None,
        "draft_body": None,
    }
    ruled = rule_decision(facts)
    if ruled:
        action, rule_id, rationale = ruled
        return {**proposal, "action": action, "decided_by": "rule", "rule_id": rule_id,
                "confidence": 1.0, "rationale": rationale}
    try:
        d = decider(facts)
    except Exception as exc:  # the quote still needs a decision; hand it to a person
        return {**proposal, "action": "escalate", "decided_by": "error",
                "rationale": f"Automatic decision failed ({type(exc).__name__}: {exc}); needs a person."}
    return {**proposal, "action": d.action, "decided_by": "llm", "confidence": d.confidence,
            "rationale": d.rationale, "draft_subject": d.email_subject, "draft_body": d.email_body}
