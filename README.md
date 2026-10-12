# margin-guard

When a supplier changes a price, every open quote that uses that material is
suddenly priced on a stale cost. Margin Guard reads vendor emails, turns each
price change into an event, finds the affected quotes, proposes what to do with
each one, and asks a person to approve. Every approval feeds an eval that
measures how far the system can be trusted to act on its own.

> Work in progress: Day 2 of 4 (coordinator, impact analysis, decisions).

## How it works (so far)

```
vendor email ──► extract (Claude, structured output)
                   │  reports only what the email says
                   ▼
                 normalize (deterministic code)
                   │  catalog match · unit conversion · % → $/lb · sanity checks
                   ▼
                 event log (SQLite, append-only, idempotent)
                   │
                   ▼
                 coordinator (LangGraph, one run per event)
                   ├─ needs_review ──────────────────────────► review item for a person
                   └─ detected ─► record change ─► impact ─► decide ─► proposals
                                                     │          │
                                       which open quotes,   rules for clear cases;
                                       margin before/after, Claude for judgment calls
                                       $ exposure, repriced  + the draft email
                                       unit prices
```

The LLM never does arithmetic or catalog lookups. Anything the code can't stand
behind (an ambiguous material name, a >30% move that smells like a unit error,
no effective date, low confidence) is routed to a person, not guessed.

### Deciding what to do with each quote

The shop's rules live in [data/pricing_policy.md](data/pricing_policy.md):

| Situation | Action | Decided by |
|---|---|---|
| Quote expires before the change takes effect | honor | rule |
| Customer's price lock covers the effective date | honor (loss logged) | rule |
| Margin still at or above the quote's floor | absorb | rule |
| Below floor: ≥ $15k or key account | contact_customer | Claude |
| Below floor: everything else | reprice (revised quote) | Claude |
| Contract note says how revisions must be communicated | follow the note | Claude |

Claude makes the judgment calls and writes the draft; every price in a draft
comes from the impact calculation. Decisions are graded against an independent
implementation of the same policy ([evals/reference_policy.py](evals/reference_policy.py)).

## The demo shop

A synthetic custom rubber-molding job shop (`margin_guard/seed.py`, deterministic):
12 materials from 7 vendors, 40 parts, 24 customers (four with price locks,
four with contract notes on how price revisions must be communicated, two with
distractor notes), 150 open quotes and 120 closed ones. The vendor inbox
(`data/vendor_emails.json`) has 15 emails, each with a gold label and the trap
it tests:

| Trap | Example |
|---|---|
| Unit conversion | $/kg, per 25 kg bag, $/cwt, $/metric ton |
| Percent-only notice | "FKM 75 up 6.5%" (new cost computed from *our* cost) |
| Duplicates | forwarded re-send; a change that was already applied |
| Ambiguous name | "Black 70" from a distributor selling both EPDM 70 and NBR 70 |
| Not a price change | holiday schedule, a new supplier's sales offer |
| Advisory | "expect 3-5% next quarter, details to follow" |

## Run it

```bash
cp .env.example .env               # add ANTHROPIC_API_KEY
python -m margin_guard.seed --reset
python -m margin_guard.ingest
python -m margin_guard.coordinator # impact + decisions for every pending event
python -m evals.eval_extraction    # scores extraction against gold labels
python -m evals.eval_decisions     # scores quote decisions against the policy
python -m pytest                   # offline tests, no API calls
```
