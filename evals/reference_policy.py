"""The answer key for quote decisions, written independently of margin_guard.decide.

Encodes data/pricing_policy.md directly. Contract notes are free text for the
agent, but here they're a hand-coded table of what each note requires, so the
eval checks whether Claude actually read and applied them.
"""

CONTACT_VALUE_THRESHOLD = 15_000

# What each customer's contract note requires when a revision is needed.
# C-11 and C-21 have notes too, but about logistics and payment terms; they
# must NOT change the decision.
NOTE_OVERRIDES = {
    "C-02": "reprice",            # "revised pricing always by email ... do not call"
    "C-07": "contact_customer",   # "must be agreed by phone ... before a revised quote is sent"
    "C-12": "reprice",            # key account, but "send revised quotes by email only"
    "C-13": "contact_customer",   # "requires a call ... before any change to quoted pricing"
}


def expected_action(f: dict) -> str:
    if f["valid_until"] < f["effective_date"]:
        return "honor"
    if f["price_lock_until"] and f["price_lock_until"] >= f["effective_date"]:
        return "honor"
    if f["margin_after"] >= f["margin_floor"]:
        return "absorb"
    if f["customer_id"] in NOTE_OVERRIDES:
        return NOTE_OVERRIDES[f["customer_id"]]
    if f["quote_value_usd"] >= CONTACT_VALUE_THRESHOLD or f["customer_tier"] == "key":
        return "contact_customer"
    return "reprice"
