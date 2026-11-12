---
version: 2
slug: "frontend-src-app-tsx"
primary_target: "frontend/src/App.tsx"
related_targets: ["frontend/src/components"]
---

Scope: the Margin Guard console (frontend/src/App.tsx and its components). Mode: Operate. Users: one primary user per screen; the owner on Home, the estimator on To decide, each report and setup page its own task. Constraints: dark only (user-pinned); a person approves everything; every figure traces to a row. User steer (2026-11-12): the redesign brief in docs/redesign/REDESIGN.md is final; the Supply Catalogue direction (2026-11-10) is retired.

## Direction contract

THESIS: A manufacturing cost tool, not a generic dark dashboard. Structure first: one user and one task per screen, a grouped sidebar, the work above the fold. The domain gives it character: the margin-floor bar, cost moves written as an estimator says them, condensed display figures.

OWN-WORLD: Soft slate (ground #1E2227, sheet #262B31, ink #DDE1E6). Three meaning colours with one job each: blue #8FB4E0 is clickable and nothing else, terracotta #E5A08C is below floor or money lost, amber #D9B777 needs a person. Inter for text, Archivo Narrow 600 for display figures only. Sentence case; no uppercase tracked labels, pill badges, coloured material squares or middle-dot strings.

STORY: The owner opens Home and sees what needs a person, which won orders will absorb increases and what has leaked. The estimator works To decide row by row: the selected quote in the panel, the margin against its floor on the bar, one Approve.

FIRST VIEWPORT: Left sidebar (Home; Queue: To decide, Settled by rules, Done; Before you quote: Quote check; Reports: Leakage, Outcomes; Setup: Supplier inbox, Imports, Shop data; dashed "Sample shop, synthetic data." box with "Open demo controls"). Home: h1, "Needs you" rows with one filled button, the one actionable customer line, the already-leaked tile with monthly bars. To decide: header with Filter and What if popovers; table of Customer, Margin now, Recommended, At risk; detail panel with sentence, margin-floor bar and At risk, cost lines, Approve, Choose another action, Reject, four collapsed sections.

FORM: The brief's eleven rules (docs/redesign/REDESIGN.md, "Rules for the whole console") are the acceptance test for every lane. The margin-floor bar appears only in the To decide panel, the Quote check verdict and a Leakage job's trace.

FINISH: DESIGN.md and .impeccable/design.json record the shipped build (2026-11-12); README screenshots in docs/screenshots are retaken from it.
