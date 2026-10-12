# margin-guard

When a supplier raises a price, every open quote built on that material is quietly losing
money. Usually nobody notices until the job is already shipped at the old margin.

Margin Guard reads the supplier's email, works out which open quotes the change hurts and by
how much, decides what to do about each one, drafts the message, and puts it in front of a
person. Agents coordinate the work and a person approves every outcome. An evaluation loop
measures when the system can be trusted, and turns every human correction into a test.

Built in four days as a working prototype on a synthetic rubber-molding shop: 150 open quotes,
24 customers, 12 materials and a supplier inbox full of traps.

## Results

| What was measured | Result |
|---|---|
| Supplier emails read correctly: the 15 the pipeline was built on | **15 / 15** (outcome, material, $/lb, date) |
| Supplier emails read correctly: 10 harder ones nothing was tuned against | **9 / 10**; the miss was sent to a person, no wrong price got through |
| Quote decisions on the full shop, vs. an independent copy of the policy | **232 / 232**: 200 settled by rules, 32 judgment calls by Claude |
| 30 hand-built judgment calls x 3 runs (Claude Sonnet 5.5) | **87 / 90** right, same answer every run, every draft passes its checks |
| ...of those, calls made with confidence ≥ 0.90 | **93% of calls, 100% right**. All 3 misses came in at ≤ 0.60 |
| Prompt injection hidden in a customer note (2 cases) | Refused both times, and **flagged the bad instruction** to the account manager |
| Cost per judgment call | **$0.009** (Sonnet 5.5) |

### Sonnet vs Haiku: calibration matters more than accuracy

| | Sonnet 5.5 | Haiku 5.5 |
|---|---|---|
| Right action | 97% | 94% |
| Same answer on every run | 100% | 93% |
| Cost per decision | $0.0088 | $0.0006 |
| Confidence on its misses | **0.55 – 0.60** | **0.90** |

Haiku is 15x cheaper and nearly as accurate, but it is wrong *confidently*. On a $30k quote it
reasoned "at or above the $15,000 threshold, but standard tier, so the rule does not apply" and
reported 0.90. Sonnet's mistakes are unsure, so its confidence can tell a reviewer which cards
to read carefully. In a human-in-the-loop system that is the property that matters, so the
console runs on Sonnet.

### What the loop learned from real reviews

In the console, a reviewer absorbed a $36 increase on a $1,124 quote instead of calling the
customer as Claude proposed. That isn't a model error. The policy never lets Claude absorb below
the floor, so `eval_approvals` reports it as a **policy signal**: if it repeats, the shop
probably wants a de-minimis rule ("absorb anything under $X at risk"). Overrides the model *can*
learn from (for example "call" changed to "email") are written out as new regression cases
automatically.

## How it works

```
supplier email ──► extract ─────────► normalize ──────────► event log
                   Claude: reports    code: match catalog,  SQLite, append-only,
                   only what the      convert units, % →    idempotent (a forwarded
                   email says         $/lb, sanity checks   copy is a no-op)
                                             │
                          anything doubtful ─┴─► "needs a look" (a person answers)
                                             │
                                             ▼
                   coordinator (LangGraph, one run per price change)
                     impact ──────────► decide ─────────────────► approval queue
                     code: which open   rules settle ~85%;        one live card per quote;
                     quotes, margin     Claude makes the          a newer change supersedes
                     before → after,    judgment calls and        an older card when its
                     $ at risk, prices  writes the draft          numbers already include it
                     that restore
                     margin
```

**Design decisions**

- **The LLM reads; code does every number.** Claude extracts what an email says and makes
  judgment calls. Unit conversion, catalog matching, margin maths and revised prices are all
  deterministic, so every figure on a card can be traced to a row.
- **Rules first.** Expired-before-the-change, price locks and above-floor increases never reach
  the model. It is only asked what the rules can't answer.
- **Refuse to guess.** An ambiguous material ("Black 70" from a distributor selling two),
  a move over 30% (usually a unit slip), a missing date or low extraction confidence goes to a
  person as a one-click question.
- **Costs stack.** A quote hit by EPDM +9.5% and carbon black +8.3% gets one card priced on both,
  and the card lists every change behind its numbers.
- **A person approves everything.** Approving a revised quote writes the new prices and queues
  the email. Approving "call first" creates a call task with the buyer's number. Every decision
  can be undone.

### The decision policy

Plain English in [data/pricing_policy.md](data/pricing_policy.md), graded against an independent
implementation in [evals/reference_policy.py](evals/reference_policy.py):

| Situation | Action | Decided by |
|---|---|---|
| Quote expires before the change takes effect | honor | rule |
| Customer's price lock covers the effective date | honor (loss logged) | rule |
| Margin still at or above the quote's floor | absorb | rule |
| Below floor, ≥ $15k or key account | call the customer first | Claude |
| Below floor, otherwise | send a revised quote | Claude |
| A contract note says how revisions must be communicated | follow the note | Claude |

## The console

Built for an estimator, not an engineer.

- **Needs your decision:** Claude's judgment calls sorted by dollars at risk, plus supplier
  emails the system wouldn't guess on. Each card says the margin move in words ("0.7 pts below
  the 27.7% floor"), who to call or email, every cost change behind the numbers, the line-by-line
  prices and an editable draft. It also says whether Claude's confidence clears the eval's bar.
  This is a report only: nothing is approved automatically.
- **Settled by rules:** honor/absorb decisions grouped by price change, confirmed in bulk.
- **Done:** what each person decided next to what was proposed, the outbox, and undo.
- **Data:** quotes, customers and materials, so any number on a card can be checked.
- **Supplier inbox:** each email's current status and what it led to ("17 quotes checked ·
  5 need you"), linked to its cards. "Send test email" drops in a new one, and the activity feed
  streams the agents working on it live.

## Evaluation

| Eval | Command | What it checks |
|---|---|---|
| Extraction | `python -m evals.eval_extraction [--set holdout]` | outcome, material, $/lb within 0.5%, date |
| Decisions on the shop | `python -m evals.eval_decisions` | every quote decision vs. the reference policy, and that drafts quote the computed prices |
| Scenario suite | `python -m evals.eval_scenarios` | 30 edge cases x 3 runs x 2 models: accuracy, consistency, draft checks, cost, calibration, the confidence bar |
| Reviews | `python -m evals.eval_approvals` | reviewer agreement by confidence; disagreements become regression cases or policy signals |

The scenario groups are the size threshold ($14,999 / $15,000 / $15,001), tier, notes that
override the rule (including one in Spanish), decoy notes that must not ("call ahead before
deliveries"), conditional notes, prompt injection, stacked changes and price holds that just
ended. All evals cache their model calls, and `--replay` rescores for free.

The offline test suite (`python -m pytest`) makes no API calls. It covers unit conversion,
catalog matching, the event log, impact maths, superseding, every reviewer action including
undo, the API, and the eval machinery itself.

## Known limitations

- **"Cents" can't be expressed.** On "118 cents per pound" Claude reported 118 per lb and noted
  the problem; the 30% guardrail sent it to a person. The fix is a schema field. It was left
  unpatched so the held-out score stays honest; it needs fresh emails to re-measure.
- **Late-arriving earlier changes.** A card for a Nov 20 change that was decided before a Nov 1
  change arrived doesn't include the Nov 1 increase. The Nov 1 card still flags it, but the
  right fix is to re-decide affected cards when an earlier-dated change lands.
- **A debatable policy edge.** On "key account + prefers email for routine changes, call over
  $10k" at $8k, Sonnet chose a call three times out of three, at 0.55 – 0.60 confidence.
  The written policy says the note wins. The console marks these cards as below the bar.
- **Synthetic data.** The shop, quotes and emails are generated, and the confidence bar comes
  from 90 runs. Real quotes and real reviews would re-set it, which is what `eval_approvals`
  is for.

## Run it

```bash
cp .env.example .env                    # add ANTHROPIC_API_KEY
python -m margin_guard.seed --reset     # build the demo shop
python -m margin_guard.ingest           # read the supplier inbox
python -m margin_guard.coordinator      # impact + decisions (--replay evals/results/decisions.json reuses cached calls)

uvicorn margin_guard.api:app --port 8000
cd frontend && npm install && npm run dev   # http://localhost:5174
```

Stack: Python 3.11, LangGraph, FastAPI + SSE, SQLite (WAL), React 19 + Vite + Tailwind, and
Claude Sonnet 5.5 through the Anthropic SDK with structured outputs.
