# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Two primary users, served equally by two distinct surfaces:

- **Estimators** at a custom manufacturing job shop. They work the approval queue daily: read each card, check the numbers, approve, edit or reject a recommended action, and send the customer communication. They read sentences, not telemetry.
- **Owners / general managers** of the same shop. They care about margin, not individual cards: how much is exposed right now, how many quotes are below the margin floor, and how much margin has leaked historically because costs moved after quoting.

Evaluators: the product is an outreach proof. The people who open and judge it are **founders and hiring engineers** at AI and manufacturing-software companies, assessing product sense and engineering judgment. It must read as a credible product to a shop owner, but the evaluator is technical.

## Product Purpose

When a supplier raises a price, every open quote built on that material quietly loses margin, and usually nobody notices until the job ships at the old price. Margin Guard reads supplier emails, finds the open quotes the change hurts, computes before/after margin and dollars at risk, recommends an action (honor, absorb, reprice, contact the customer), drafts the communication, and puts every outcome in front of a person for approval.

Success: a shop catches margin erosion before it ships, and the owner can see in dollars what was protected. As an outreach proof, success is an evaluator concluding this is a real product solving a real market problem, not a standalone demo.

## Positioning

The LLM reads; code does every number. Claude extracts what an email says and makes the judgment calls; unit conversion, catalog matching, margin maths and revised prices are deterministic and traceable to a row. A promotion gate measures, with a noise floor, when a policy or model change is safe to ship, and a correction ledger keeps "is it safe" apart from "is it wanted". The customer is buying protection against lost profitability, not an AI agent.

## Operating Context

- Market: custom manufacturing job shops that quote from a BOM. Rubber molding is the demo dataset, not the whole market.
- Workflow: supplier email → extraction → normalization (catalog match, units, sanity checks) → append-only event log → impact → rules-first decision, Claude for judgment calls → approval queue → outbox / call task → outcome.
- Console lanes today: Needs your decision, Settled by rules, Done (with undo), Data, Supplier inbox with a live activity feed.
- Doubtful inputs (ambiguous material, >30% move, missing date, low confidence) go to a person as a one-click question rather than being guessed.

## Capabilities and Constraints

- Stack: FastAPI-style Python backend (`margin_guard/`), SQLite, LangGraph coordinator; React 19 + Vite + Tailwind 4 console (`frontend/`).
- A person approves everything; nothing is approved automatically. Every decision can be undone.
- Exposure is replacement-cost exposure (material bought when the order is placed); inventory-aware costing is out of scope.
- Planned (2026-11): vendor-specific costing, Decimal money with cents support, effective-date timeline recompute, CSV import, a retroactive margin-leakage report, PDF/Excel price-sheet extraction, invoice price drift, a quote-time warning, an owner-facing exposure view.
- Out of scope for the proof: Gmail/Outlook OAuth, ERP connectors, multi-tenant/RBAC.
- Terminology: quote, quote line, BOM, margin floor, exposure / dollars at risk, honor / absorb / reprice / contact customer, card, superseded, costing vendor.

## Brand Commitments

- Name: **Margin Guard**.
- Voice: plain English for estimators; margin moves stated in words ("0.7 pts below the 27.7% floor"); honest about limits.

## Evidence on Hand

- Measured results in `README.md` and `evals/results/` (extraction 15/15 tuned, 9/10 holdout; 232/232 decisions; scenario suite; promotion gate report and correction ledger).
- All shop data is **synthetic** (150 open quotes, 24 customers, 12 materials). There are no real customers, testimonials, pilots or revenue; never imply otherwise.
- Illustrative dashboard figures (e.g. "$42.8K at risk") are concepts, not repository data, unless computed from the seeded shop.

## Product Principles

1. Every number is traceable to a row; the model never computes money.
2. Refuse to guess: doubt goes to a person, not into a margin.
3. A person approves every outcome, and their corrections become tests.
4. Show business value in dollars: margin protected and margin at risk.
5. Honest limits over impressive claims; label synthetic data and assumptions.
