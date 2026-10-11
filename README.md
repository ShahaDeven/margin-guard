# margin-guard

When a supplier changes a price, every open quote that uses that material is
suddenly priced on a stale cost. Margin Guard reads vendor emails, turns each
price change into an event, finds the affected quotes, proposes what to do with
each one, and asks a person to approve. Every approval feeds an eval that
measures how far the system can be trusted to act on its own.

> Work in progress: Day 1 of 4 (data, email extraction, event log).

## How it works (so far)

```
vendor email ──► extract (Claude, structured output)
                   │  reports only what the email says
                   ▼
                 normalize (deterministic code)
                   │  catalog match · unit conversion · % → $/lb · sanity checks
                   ▼
                 event log (SQLite, append-only, idempotent)
                   ├─ price_change.detected      → coordinator (Day 2)
                   └─ price_change.needs_review  → human queue
```

The LLM never does arithmetic or catalog lookups. Anything the code can't stand
behind (an ambiguous material name, a >30% move that smells like a unit error,
no effective date, low confidence) is routed to a person, not guessed.

## The demo shop

A synthetic custom rubber-molding job shop (`margin_guard/seed.py`, deterministic):
12 materials from 7 vendors, 20 parts, 10 customers (two with contract price
locks), 45 open quotes and 30 closed ones. The vendor inbox
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
python -m evals.eval_extraction    # scores extraction against gold labels
python -m pytest                   # offline tests, no API calls
```
