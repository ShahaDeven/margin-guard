# Margin Guard: catch supplier price increases before they eat your margin

A custom manufacturer quotes a job at a 30% margin, valid for 60 days. Three weeks later the
rubber supplier emails: EPDM goes up 8% on November 1. The quote is still open. The customer
accepts on November 10, the job ships at the old price on the new cost, and the margin quietly
drops below what the shop will accept. Nobody notices until month-end, if at all. Multiply that
by every open quote that uses EPDM, and by every supplier.

**Margin Guard reads the supplier's email (and the price list attached to it), finds every open
quote the change hurts, works out by how much, decides what to do about each one, drafts the
message, and puts it in front of a person.** Rules settle the clear cases, Claude makes the
judgment calls, code does every number, and a person approves everything. It also looks at the
same problem from three other sides: before a quote goes out, when a supplier raises a price
without saying so, and after the job has shipped.

*Everything here runs on a synthetic shop: 150 open quotes, 120 closed ones, 24 customers,
12 materials, a year of price history and a supplier inbox full of traps. There are no real
customers behind any number. Rubber molding is the demo; anything quoted from a bill of
materials fits.*

![To decide: quotes below their floor in one table, the selected one in a panel with the margin-floor bar, the costs that moved and one Approve button](docs/screenshots/queue.png)

## Quick start

Python 3.11+ and Node 20.19+. No API key needed: the commands below replay Claude's answers,
which are cached in `evals/results/`.

```bash
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # requirements-dev.txt adds pytest, matplotlib, pymupdf

# Build the demo shop and run the agents on its inbox (no API calls).
python -m margin_guard.seed --reset
python -m margin_guard.ingest --replay evals/results/extractions.json
python -m margin_guard.coordinator --replay evals/results/decisions.json

# The console
uvicorn margin_guard.api:app --port 8000
cd frontend && npm install && npm run dev      # second terminal: http://localhost:5174
```

`seed --reset` refuses while the API server has the database open (Windows locks the file):
stop uvicorn, rebuild, start it again. Run the tests with `python -m pytest` (no API calls).

**Try it (about five minutes):** the console opens on **Home**, the owner's page: what needs a
person, which won orders will absorb increases, and what has already leaked.
1. **To decide.** Press **Start deciding**. Each row is one quote below its floor; the selected one
   opens in the panel on the right: one sentence on what happened, the margin-floor bar (quoted,
   now and the floor, on one line) with dollars at risk beside it, and the costs that moved
   ("FKM 75, $14.80 → $15.76/lb, Dec 1"). **Why Claude recommends this**, the line prices, the
   draft and the customer's record are one click down. Press **J** and **K** to move through the
   rows, and try **What if increases were bigger** to see every margin at 1.5 times.
2. **A supplier question.** The "Black 70" email sits at the top as **Answer a question**: the
   distributor sells two compounds by that name, so the system asks instead of guessing. Pick one;
   it becomes a price change, and the agents check every open quote that uses it.
3. **Quote check.** A 60-day quote for 2,500 HVAC duct boots at 30% margin. An increase on Nov 1
   lands inside it. Click **Use 16 days**, and the check comes back clear.
4. **Leakage.** **Orders still to buy**: 13 won orders whose material isn't bought yet; 7 absorb
   increases, $1,682 in total. Their prices are fixed, so nothing can be revised. Open
   **Prairie Ag Equipment** (Q-2026-0351): the Nov 15 SBR 60 increase costs it $989, and **Buy now**
   records buying its material before the increases land (undo is next to it). **Already
   leaked**: $6,151 on won jobs. Click **1018 steel**, then **Trace** on a job: the margin-floor
   bar, every line, the cost at quote and at order, and the price-history row behind each.
5. **Imports.** Choose **or try a sample file**, then the messy accounts-payable export: its own
   column names, US dates and "LBS"/"CWT"/"TON" units. The columns are matched for you. Match "GLE"
   to Great Lakes Elastomers and "EPM70 BLK" to EPDM 70, and mark Freight as not an item you stock.
   The check shows what an import would do (8 lines, 3 above quoted cost, $495.93 overpaid) before
   anything is written. Press **Import**, then open the new decisions in To decide: Ridgeline billed
   carbon black at $1.14/lb against $1.09 on file, with no price notice. **Apply** it as a price
   change, or **Dismiss** it.
6. **Outcomes.** Approve a **Send a revised quote** row in To decide (the panel's "This customer's
   past increases" says how they took the last ones). In **Done**, open it and record what the
   customer said: **Accepted**, **Negotiated** (type the dollars they agreed to) or **Walked**.
   **Outcomes** shows recovered against asked, the revenue walked away, and every customer's record.

With an `ANTHROPIC_API_KEY` in `.env`, **Open demo controls** at the foot of the sidebar and
**Send test email** reads a new supplier email live (about a cent; D4 is a PDF price letter).
Without a key it fails gracefully: the email shows "could not read" and any judgment call becomes a
decision for a person.

## One price change, end to end

On October 13, Midwest Polymer emails: *EPDM 70 compound goes from $2.10/lb to $2.27/lb on
November 1.* Here is what happens to it.

1. **Read.** Claude reports what the email says (the material as written, the price, the unit,
   the date) and nothing else. It does not convert units or work out new prices.
2. **Check.** Code matches "EPDM 70 duro compound" to the catalog, confirms Midwest is the
   supplier EPDM 70 is costed at, converts to $/lb, and checks the move is believable (+8.1%,
   inside the 30% bound that catches unit slips). The change goes into an append-only log; a
   forwarded copy of the same email the next day is recognized and does nothing.
3. **Impact.** Code finds the 20 open quotes with a part made of EPDM 70 and recomputes each one
   at the new cost, stacked with any other change on file by the same date. Quote Q-2026-0204 for
   Lakeshore HVAC (2,500 duct boots, $16,441.75) also uses carbon black, and two days later
   Ridgeline's email moves carbon black up on Nov 1 as well, so the card is restated with both:
   unit cost $4.6563 to $4.8635, margin 29.2% to 26.05%, below its 28.2% floor. $517.88 at risk;
   $6.8693 a unit would restore the margin.
4. **Decide.** Rules settle 16 of the 20: three quotes expire before November 1 (honor), thirteen
   stay above their floor (absorb). The other four are judgment calls. Lakeshore is a key account
   over $15,000, so the policy says call before sending a revised price; Claude writes the call
   brief for the account manager, quoting the computed numbers.
5. **Approve.** In the console the estimator reads the decision, edits the draft if needed, and
   approves. That creates a call task with the buyer's name and number. Nothing is sent and no
   price changes until a person says so, and every decision can be undone.

Every figure on that card can be traced back to a row, and the eval checks that every draft
quotes the computed prices.

## How it works

![System design: supplier email and attached price lists, invoice export and shop data come in; Claude extracts what was written; code normalizes it into an append-only event log and price history; a coordinator works out impact, restates late arrivals and decides; doubtful inputs go to a person; the approval queue leads to the outbox; quote check and leakage read the same record; every verdict feeds the eval loop](docs/architecture.png)

Violet is Claude, orange is a person, green is the record everything else reads, grey is code.
Top to bottom:

1. **What comes in:** supplier emails with any attached price list (.xlsx, .csv, .pdf), an
   accounts-payable invoice export, and the shop's own data (nine CSVs, or the demo seed).
2. **Read, the first AI step:** code turns attachments into text (every sheet's rows; a PDF's
   text layer). Claude reads the email and that text and reports only what is written.
3. **Normalize, no AI:** catalog matching, units to $/lb, cents and currency, the sanity bound,
   and the costing supplier. Anything doubtful goes to a person as a one-click question.
4. **The record:** an append-only event log and the price history, in SQLite. Everything after
   this reads from it.
5. **Coordinator (LangGraph), one run per price change:** impact on every open quote, then
   restatement of any later-dated card the change makes stale, then the decision: rules first,
   Claude only for the judgment calls and the draft.
6. **A person** approves, edits, rejects or undoes. Every verdict feeds the eval loop.

The diagram's source is [`docs/architecture.mmd`](docs/architecture.mmd) (Mermaid);
`python -m evals.render_diagram` re-draws the PNG.

**What the design guarantees, and what it doesn't:**
- **The model never computes money.** Claude reads and judges; unit conversion, matching,
  margins, dollars at risk and revised prices are Decimal arithmetic in code, rounded half-up
  once, so every figure traces to a row.
- **Doubt goes to a person, not into a margin.** An ambiguous material ("Black 70" from a
  distributor selling two), a move over 30% (usually a unit slip), a missing date, a price in a
  foreign currency, or low extraction confidence becomes a question, never a guess. Every
  attachment is marked complete, truncated, unreadable or failed; anything but complete always
  raises a review, even when the email body gave a valid change, so a partial read is never
  presented as the whole file.
- **Exactly one costing supplier per material, and it fails closed.** A shop can buy EPDM 70
  from two suppliers, but quotes are costed at one price. Every supplier's prices are recorded; only
  the costing supplier's move margins. A distributor's pass-through increase shows as "alternate
  supplier, on file". The database refuses a second costing supplier, the import refuses a material
  with none, and if one is ever missing no supplier's price moves that material's margins (the
  console shows a red banner) rather than another supplier's being picked silently.
- **Arrival order doesn't matter.** Supplier emails don't come in date order (the demo inbox has a
  Nov 15 change arriving before a Nov 1 one). When an earlier-dated change lands, every pending
  card dated after it is recomputed, re-decided and replaced, and the old card says why. The
  shop's inbox processed in arrival, date, reverse and random orders gives identical live cards.
- **Costs stack.** A quote hit by two changes gets one card priced on both, listing each.
- **A person approves everything.** Nothing is approved automatically, whatever the confidence.
- **Not guaranteed:** a person who approves without reading, a supplier price that was never
  emailed or invoiced, and stock already on hand (exposure is replacement cost).

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

## Before, during, and after a price change

The queue handles a change once it's announced. Three more views look at the same problem from
the other sides.

### Before the quote goes out: Quote check

The cheapest leak to fix is the one in a quote you haven't sent. **Quote check** takes a draft
quote (customer, parts, quantities, prices, validity) and reads the increases already on file:
which ones take effect before the quote expires, and the margin if the customer orders on or
after each. It judges the quote by its worst point, not its last: an increase later partly
reversed still exposes every order placed while it lasts. It offers three ways out: a validity that ends the day before the first increase, the
prices that hold each line's margin through every increase, and an escalation clause naming each
material's quoted and announced price. It flags a customer price lock that covers an increase
(an escalation clause may not hold) and any supplier email about these materials still waiting
for a person. The 2,500-duct-boot example: 30% falls to 26.9% after Nov 1, $518 at risk; valid
16 days instead, it's clear. Nothing is saved; quotes live in the shop's own system.

![Quote check: an increase on Nov 1 lands inside a 60-day quote; the margin-floor bar shows the quoted and worst margin against the floor, and the ways out are a 16-day validity, a held price, or an escalation clause](docs/screenshots/quote-check.png)

### When nobody announced it: invoice drift

Not every supplier sends a notice; sometimes the first sign is the invoice. The invoice check
reads an accounts-payable export and compares each line with that supplier's price on file for
the invoice date. A line billed more than 0.5% above it becomes a card with the invoices, that
supplier's price on file and the history row it came from, and the dollars overpaid. Later
invoices at the same price join the open card; once a person has decided it, new ones raise a
new card and the decision stands. **Apply** records the
billed price as a price change from the first invoice date, and the normal impact and decisions
run; **Dismiss** changes nothing (a one-off, or an error to dispute). Items we don't stock,
ambiguous items and suppliers with no price on file are listed, not guessed. The demo export:
12 lines, two drifts (Ridgeline N550 on two invoices, Summit VMQ 50 by the bag), $728.21 overpaid.

In the console, the **Imports** view takes the export as it comes out of the accounting system,
in four steps:

1. **Columns.** Each field gets a suggested column ("Doc No" becomes the invoice number, "UoM"
   the unit), which you can change.
2. **Suppliers.** Each supplier name in the file is matched to one on file by id, name or email
   domain. A name it can't place, such as "GLE", is asked about rather than guessed.
3. **Items.** An item the catalog can't place is matched by hand, or marked as not an item you
   stock. Ticking **Remember** saves the match as an alias, so the next file matches by itself.
4. **Check.** Every row is validated and the whole import runs as a dry run inside a rolled-back
   savepoint. The screen shows exactly what pressing Import will write.

**Import** then writes everything in one transaction: the invoice lines, the cards (or invoices
added to cards already open), and the remembered matches. Every import, committed or
discarded, is kept in the history with its mapping and summary. The command line runs the same
code:

```bash
python -m margin_guard.invoices check data/invoices_demo.csv
python -m margin_guard.coordinator             # puts the drift cards in front of a person
```

### After the increase went out: what the customer did

Approving a reprice or a call is not the end of it; the customer answers. In **Done**, every
approved reprice email and call asks for that answer: **accepted**, **negotiated** (the dollars
they agreed to), or **lost the job**. The quote follows what was agreed, so the next price change
is checked against real prices. Accepting a call writes the revised prices. A negotiation moves
each line by the same share of its increase. A lost job takes the quote out of the open quotes.
Every response can be undone, and undoing a decision waits until its response is undone.

The **Outcomes** view answers the owner's question, "does repricing work?":

- dollars recovered against dollars asked on the jobs the customer stayed on;
- the revenue lost when one walked;
- what is still waiting for an answer;
- each customer's record ("usually pushes back", "has walked over increases").

That record also sits in the To decide panel, under "This customer's past increases", so the person
approving a reprice sees how this customer took the last ones.

It is shown to people and never given to the model: no decision prompt changed, so every cached
decision and eval still holds. Whether a customer's record *should* change the decision is a
policy change, and it would go through the promotion gate like any other.

The demo shop ships with 43 responses from before Margin Guard (synthetic, like the rest of the
data): $20,797 recovered of $24,407 asked on the jobs kept (85%), and 6 jobs lost, worth $165,490.

```bash
python -m margin_guard.outcomes             # the summary in the terminal; also /api/outcomes
```

### Won, but the material isn't bought yet

A won order's price is fixed by the customer's purchase order. If its material is bought when the
job is scheduled, every increase that takes effect before then comes out of its margin, and
nothing in the queue asks about it: impact looks at open quotes, and leakage at the gap between
quote and order.

So a won order can carry a planned **material buy date**. For each one, the costing supplier's
price is compared at three dates: as ordered, today, and at the buy date. The increases already
on file move the buy-date cost the day they're processed. On the demo shop, after the inbox:

- **13 won orders** ($212,027) are waiting for material, and 7 of them will absorb **$1,682**;
- one drops below its margin floor;
- decreases give $789 back on two others.

The only lever left is timing. **Buy now** records the order's material as bought today, at
today's cost; on the demo that keeps **$1,657**. It is suggested only when an increase still to
come lands before the buy date, never ahead of a decrease. Whether the cash and the storage are
worth it stays a person's call, and every early buy can be undone.

An order with no buy date counts as bought on its order date, the same assumption as leakage and
impact, so neither figure moves. In `quotes.csv` it is an optional `material_buy_date` column.

```bash
python -m margin_guard.backlog              # the backlog in the terminal; also /api/backlog
```

### After the job shipped: margin leakage

The owner's question: how much margin did won jobs already lose because costs moved after we
quoted? For each won quote, the leakage report compares the material cost the price was built on
with the cost on the day the customer ordered. On the demo shop: **$6,151 leaked on 56 of 88 won
jobs**, margin 29.4% as quoted and 28.9% as ordered, one job pushed below its floor. **$4,617 was
recoverable** by a revised quote in time; the other $1,535, on 16 jobs, was locked in by customer
price locks (the contract gave it away; it wasn't missed). In the console every figure opens the
jobs behind it, and every job opens a line-by-line trace to the price-history rows and the
supplier email when there was one. A job whose materials have no history back to its quote date
is listed and left out, not costed at today's price.

| An increase found on an invoice | Leakage traced to the rows |
|---|---|
| ![Invoice drift question: on file $1.09/lb, billed $1.14/lb on two invoices, $350 overpaid](docs/screenshots/invoice-drift.png) | ![Leakage trace: the margin-floor bar, then each quote line with its cost at quote and at order and the price-history row behind it](docs/screenshots/leakage-trace.png) |

```bash
python -m margin_guard.leakage              # the report in the terminal; also /api/leakage
```

## The console

One primary user and one task per screen. Dark only, in a soft slate: a dim grey ground, off-white
text and muted accents. Colour has one job each: blue is something you can click, terracotta is
below the floor or money lost, amber needs a person; everything else is plain text. Each screen
has one filled button. The visual system is in [DESIGN.md](DESIGN.md), from the brief in
[docs/redesign/REDESIGN.md](docs/redesign/REDESIGN.md).

A left sidebar groups the views, each with its own URL (`#home`, `#decide`, `#leakage`, ...):

- **Home** (the owner's page, where the console opens): what needs a person, with a count, a
  sentence and a button for each kind of work; the customer with the most at risk; and margin
  already leaked on won jobs, by order month.
- **Queue.** **To decide**: one table (customer, margin now and the gap to the floor, recommended
  action, dollars at risk), supplier questions at the top, and the selected row in a detail panel
  with the margin-floor bar, the costs that moved and one Approve; Claude's reasoning and
  confidence (and whether it clears the eval's bar), the line prices, the editable draft and the
  customer's record are collapsed under it. Filter and the what-if control sit in the header;
  J / K move the selection. **Settled by rules**: one row per price change, costliest first,
  confirmed one at a time or all at once. **Done**: what each person decided next to what was
  proposed, the outbox, undo, and the customer's response to every reprice and call.
- **Before you quote. Quote check**: will a price change already on file land while a new quote is
  valid, and the ways out.
- **Reports. Leakage**: won orders still to buy material for (with **Buy now**), and margin already
  lost on won jobs, each job traced to its rows. **Outcomes**: recovered against asked, revenue
  lost, and each customer's record.
- **Setup. Supplier inbox**: each email's status and what it led to ("26 quotes checked, 2 need
  you"), its attachments (each opens the original file), and any price-list rows it left out.
  **Imports**: an invoice export matched, checked as a dry run, then written in one step, with
  earlier imports. **Shop data**: quotes, customers and materials, so any number can be checked.

The demo controls (a test supplier email and the agents' live activity) are in a drawer behind
**Open demo controls**, out of the working layout.

## How far to trust it

| What was measured | Result |
|---|---|
| Supplier emails read correctly: the 15 the pipeline was built on | **15 / 15** (outcome, material, $/lb, date) |
| Supplier emails read correctly: 10 harder ones nothing was tuned against | **9 / 10**; the miss was sent to a person, no wrong price got through |
| Cents, currency and pack emails (regression set, written with the fix) | **7 / 7**: 121¢/lb, 88.5 cents, $ with old price in cents, $/cwt, 50 lb bag; CAD and EUR sent to a person |
| Price lists and letters as attachments (.xlsx and .pdf; regression set written with the feature) | **4 / 4** changes right (per kg, per cwt, per short ton; grades we don't buy left out). The live run scored 3 / 4 outcomes: Claude called the scanned PDF "other", so a rule now sends any unreadable supplier attachment to a person; 4 / 4 is that same Claude output rescored |
| Quote decisions on the full shop, vs. an independent copy of the policy | **282 / 282**: 246 settled by rules, 36 judgment calls by Claude, every draft quoting the computed prices |
| Cards stale because an earlier-dated change arrived later (the demo inbox is out of date order) | **50** restated and re-decided; live cards identical across arrival, date, reverse and random orders |
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
reported 0.90. Sonnet's mistakes are unsure, so its confidence can tell a reviewer which cards to
read carefully. In a system where a person approves everything, that is the property that
matters, so the console runs on Sonnet.

### What the loop learned from real reviews

In the console, a reviewer absorbed a $36 increase on a $1,124 quote instead of calling the
customer as Claude proposed. That isn't a model error. The policy never lets Claude absorb below
the floor, so `eval_approvals` reports it as a **policy signal**: if it repeats, the shop probably
wants a de-minimis rule ("absorb anything under $X at risk"). Overrides the model *can* learn from
(for example "call" changed to "email") are written out as new regression cases automatically.

### When is a change safe to ship?

A correction suggests a change: a new rule, a policy edit, a cheaper model. But Claude doesn't
answer the same way every time, so one before/after run can't tell a regression from noise. The
promotion gate replays each candidate change against 62 cases (the 30 scenarios plus a frozen
snapshot of the shop's 32 judgment calls), 8 times each, and decides **promote / hold / reject**
per case, with a noise floor measured by replaying the unchanged system against itself.

| Finding | |
|---|---|
| With nothing changed, one run vs another flags a "regression" | **48%** of the time, all from 2 of 62 cases that wobble on their own |
| The gate (per-case Fisher test, false-discovery control, noise floor) on the same no-op | **0%** false alarms at every replay count |
| Replays per case before the correct change is promoted | **4** (it fixes 7 targets, 0 regressions) |
| The same de-minimis rule written as prompt text instead of code | fixes the same 7, **breaks 7 others**; aggregate accuracy calls it a wash (CI crosses 0) |
| Deliberately bad "tidy-up" policy edits (controls) | never promoted at any replay count; rejected at 8 |
| Sonnet → Haiku swap | **hold**: 6 cases got worse, none conclusively yet |

![Probability of promoting each change, by number of replays](evals/results/promotion/charts/replays_needed.png)

Every proposed change goes into a **[correction ledger](evals/results/promotion/ledger.md)** that
keeps two questions apart: is it *safe* (the gate) and is it *wanted* (what reviewers did on the
cards it would change). The de-minimis rule passes the gate but is **held**: across 55 later
reviews nobody absorbed a small increase, so its only support is the one override that suggested
it. Reviewer corrections are noisy too: the same customer note drew opposite overrides. Full
write-up: **[promotion report](evals/results/promotion/promotion_report.md)**.

The replays and the 55 reviews are committed, so all of this regenerates with no API key:

```bash
python -m evals.promotion.report         # gate verdicts, replays-needed curve, charts (~1 min)
python -m evals.promotion.ledger         # correction ledger (append-only, versioned)
```

Re-running the replays live needs `ANTHROPIC_API_KEY`: `python -m evals.promotion.replay --batch
--dry-run` prices it first (all 7 candidates at K = 8, baseline at 16: about $13 through the
Message Batches API).

### All the evals

| Eval | Command | What it checks |
|---|---|---|
| Extraction | `python -m evals.eval_extraction [--set holdout\|fresh\|attachments]` | outcome, material, $/lb within 0.5%, date |
| Decisions on the shop | `python -m evals.eval_decisions [--replay\|--fill]` | every quote decision vs. the reference policy, and that drafts quote the computed prices |
| Scenario suite | `python -m evals.eval_scenarios` | 30 edge cases x 3 runs x 2 models: accuracy, consistency, draft checks, cost, calibration, the confidence bar |
| Reviews | `python -m evals.eval_approvals` | reviewer agreement by confidence; disagreements become regression cases or policy signals |
| Promotion gate | `python -m evals.promotion.replay --batch` | replays candidate changes K times per case (Message Batches API, cached prompt) |
| Gate report | `python -m evals.promotion.report` | per-case verdicts, noise floor, replays-needed curve, cost; no API calls |
| Correction ledger | `python -m evals.promotion.ledger` | each proposed change: safe (gate) vs wanted (reviews), versioned |

The scenario groups are the size threshold ($14,999 / $15,000 / $15,001), tier, notes that
override the rule (one in Spanish), decoy notes that must not ("call ahead before deliveries"),
conditional notes, prompt injection, stacked changes and price holds that just ended. All evals
cache their model calls, and `--replay` rescores for free.

The offline test suite (`python -m pytest`) makes no API calls. It covers unit conversion and
Decimal money, catalog matching, supplier-specific costing, the event log, impact maths,
superseding and restatement, every reviewer action including undo, attachments, invoice drift,
the quote check, the leakage report and its trace, the CSV import, the console invoice import,
customer outcomes, the won-order backlog, the API, and the eval machinery itself.

## Bring your own data

A shop is nine CSV files (suppliers, materials, which supplier each material is costed at, price
history, parts, BOMs, customers, quotes with an optional material buy date, quote lines). [`data/shop_csv/`](data/shop_csv/) is the
demo shop exported in that format, so it doubles as the template.

```bash
python -m margin_guard.importer check data/shop_csv            # validate only
python -m margin_guard.importer import my_shop/ --db mine.db   # validate, then load a new database
python -m margin_guard.importer export out/                    # any database back to CSV
python -m margin_guard.leakage --db mine.db                    # the leakage report on your data
```

The import is all-or-nothing: every row is checked (dates, ranges, references between files,
duplicates, exactly one costing supplier per material, a won quote needs an order date), and if
anything is wrong nothing is written and each problem is listed by file, row and column. A blank
`material_cost_basis` is computed from the BOM and price history at the quote date. Export then
import reproduces the demo shop exactly.

## Known limitations

- **The holdout was scored before cents existed.** On "118 cents per pound" (H07) Claude reported
  118 per lb and noted the problem; the 30% bound sent it to a person. The schema now has
  `price_in_cents` and `currency`. The 9 / 10 holdout score is the pre-fix, blind result, kept as
  is; the fix is measured on the separate 7-email set, which was written with the fix and so is
  not blind.
- **Attachments: text only.** Scanned PDFs, images and legacy .xls files aren't read (no OCR);
  they're flagged and sent to a person. The 4-email attachment set was written with the feature.
- **Approved decisions are corrected, not reversed.** Pending cards are restated when an
  earlier-dated change lands. A card a person already approved is never changed (prices it wrote
  and messages it queued stay on record). Instead a linked correction card shows the decision's
  original and revised numbers side by side, and a person either keeps the decision or re-decides
  the quote, which raises a new card. Corrections under $1 that don't cross the floor aren't raised.
- **The promotion gate's shop cases predate restatement.** `data/replay_cases_shop.json` is a
  frozen snapshot taken before restatement existed, so the gate stays comparable with the
  committed replays.
- **A debatable policy edge.** On "key account + prefers email for routine changes, call over
  $10k" at $8k, Sonnet chose a call three times out of three, at 0.55 – 0.60 confidence. The
  written policy says the note wins. The console marks these cards as below the bar.
- **Replacement cost, USD only.** Exposure assumes material is bought when the order is placed,
  or on a won order's planned buy date; stock on hand isn't modelled. Money is exact (Decimal, half-up), but there is no FX conversion.
- **Synthetic history and data.** The year of price history, the won jobs' order dates,
  customers' price locks (current lock only; no lock history), their responses to past
  increases and the won orders' material buy dates are generated. The methods are the
  point; the dollar figures are only as real as the data. The confidence bar comes from 90 runs;
  real quotes and reviews would re-set it, which is what `eval_approvals` is for.

## What I would build next

- **Customer outcomes as policy evidence:** a candidate rule such as "don't reprice customers who
  have walked over increases" scored against recorded outcomes, then sent through the promotion
  gate. Today outcomes are only read by people.
- **OCR for scanned price sheets,** behind the same "unreadable goes to a person" rule.
- **Shop data through the console:** the nine-CSV onboarding on the same match → check → commit
  flow as invoice imports (today it is command line only).
- **A real inbox and quoting system** (Gmail or Outlook, an ERP connector) in place of the demo
  inbox and the CSV import.

Stack: Python 3.11, LangGraph, FastAPI + SSE, SQLite (WAL), openpyxl and pypdf for attachments,
React 19 + Vite + Tailwind 4 with self-hosted Inter and Archivo Narrow, and Claude Sonnet 5.5 through the
Anthropic SDK with structured outputs.
