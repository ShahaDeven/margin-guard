# Pricing policy: supplier cost changes on open quotes

Applies when a supplier cost change raises the cost of an open quote.

## Handled automatically by rules (listed for context)

1. The quote expires before the cost change takes effect: **honor** the quote as issued.
2. The customer's contract price lock covers the effective date: **honor**, and log the margin loss.
3. The quote's margin after the change is still at or above its margin floor: **absorb** the increase.

## When the margin falls below the floor

Choose one action:

- **contact_customer**: the account manager calls the customer before any revised price goes out.
  Use this when the quote is worth **$15,000 or more**, or the customer is a **key account** (tier = key).
- **reprice**: send the customer a revised quote by email with the proposed prices.
  Use this in every other case.

## Drafts

- **reprice**: an email to the customer's buyer, addressed by name. Reference the quote ID, explain the
  supplier cost changes in one or two sentences, and list each revised line with its new unit price.
  Keep it short and courteous.
- **contact_customer**: an internal note to the account manager. Start with who to call and their phone
  number (the buyer). Then say what changed, the margin impact in points and dollars, the proposed prices,
  and two or three talking points for the call.

A quote can be hit by more than one cost change; `cost_changes` lists all of them, and each line's
`changed_materials` says which ones affect it. Explain every change that moves a price, not only the
one that triggered the review.

Refer to materials by `material_name` (for example "Silicone (VMQ) 50 Shore A compound"), never by
their internal ID such as MAT-VMQ-50. Write dates the way a person would ("November 1"), not as ISO dates.

Use the `proposed_unit_price` values exactly as given. Never calculate prices yourself.
