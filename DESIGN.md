---
name: Margin Guard
description: A manufacturing cost tool in soft slate; one primary user per screen, the margin-floor bar as its one signature chart, and colour that only ever means one thing.
colors:
  ground: "#1e2227"
  sheet: "#262b31"
  sheet-raised: "#2e353d"
  nav-active: "#313945"
  rule: "#363c44"
  rule-soft: "#30363d"
  rule-bright: "#4a525c"
  ink: "#dde1e6"
  ink-dim: "#9ea7b3"
  go: "#8fb4e0"
  go-soft: "#b4ccea"
  stop: "#e5a08c"
  attn: "#d9b777"
typography:
  page-title:
    fontFamily: '"Inter", ui-sans-serif, system-ui, "Segoe UI", sans-serif'
    fontSize: "28px"
    fontWeight: 700
    lineHeight: 1.2
  panel-title:
    fontFamily: '"Inter", ui-sans-serif, system-ui, "Segoe UI", sans-serif'
    fontSize: "20px"
    fontWeight: 700
    lineHeight: 1.3
  section-title:
    fontFamily: '"Inter", ui-sans-serif, system-ui, "Segoe UI", sans-serif'
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.4
  body:
    fontFamily: '"Inter", ui-sans-serif, system-ui, "Segoe UI", sans-serif'
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  secondary:
    fontFamily: '"Inter", ui-sans-serif, system-ui, "Segoe UI", sans-serif'
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  group-label:
    fontFamily: '"Inter", ui-sans-serif, system-ui, "Segoe UI", sans-serif'
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.35
  figure:
    fontFamily: '"Archivo Narrow", "Inter", ui-sans-serif, system-ui, sans-serif'
    fontSize: "34px"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
rounded:
  control: "6px"
  panel: "8px"
  tile: "10px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  section: "28px"
components:
  button-primary:
    backgroundColor: "{colors.go}"
    textColor: "{colors.ground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.go-soft}"
  button-outline:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    borderColor: "{colors.rule-bright}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "44px"
  input-field:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    borderColor: "{colors.rule-bright}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  nav-sidebar:
    backgroundColor: "{colors.sheet}"
    width: "230px"
  nav-item-active:
    backgroundColor: "{colors.nav-active}"
    textColor: "{colors.go-soft}"
    rounded: "{rounded.control}"
    padding: "9px 10px"
  table:
    backgroundColor: "{colors.sheet}"
    borderColor: "{colors.rule}"
    rounded: "{rounded.panel}"
  tile:
    backgroundColor: "{colors.sheet}"
    rounded: "{rounded.tile}"
    padding: "20px"
  segmented-selected:
    backgroundColor: "{colors.nav-active}"
    textColor: "{colors.go-soft}"
---
# Design System: Margin Guard

## Overview

**North Star: "The cost sheet on the estimator's desk."** The console is a manufacturing cost tool, not a generic dark dashboard. It is set in a soft slate: a dim grey ground, off-white text and muted accents, so nothing glares through a working day. Its character comes from the domain, not from chrome: the margin-floor bar, cost moves written the way an estimator says them ("EPDM 70, $2.10 → $2.27/lb, Nov 1"), and figures set in a condensed face.

The structure follows one idea: **one primary user and one primary task per screen.** Home is for the owner; To decide is for the estimator; reports and setup each have their own page in a grouped left sidebar. Demo and simulation controls never sit in the working layout.

The full brief, with the reasoning and every screen, is [docs/redesign/REDESIGN.md](docs/redesign/REDESIGN.md). This file records what was built.

**Key characteristics**
- Dark only, soft slate. No light theme.
- A 230px left sidebar grouped Queue, Before you quote, Reports, Setup, with Home on top.
- Three meaning colours, one job each: blue is clickable, terracotta is below floor or money lost, amber needs a person.
- One filled button per screen.
- The margin-floor bar is the one signature chart, used in three places only.
- Inter for text; Archivo Narrow 600 for display figures only.
- Sentence case everywhere: no uppercase tracked labels, no pill badges, no middle-dot strings.

## Rules for the whole console

These apply to every lane. A lane that breaks one is not done.

1. **One primary user and one task per screen.** To decide is for the estimator, Home for the owner.
2. **A list row shows only what is needed to pick the next row.** Everything else lives in a detail panel or behind a click.
3. **One filled button per screen.** On To decide it is Approve; on Home, Start deciding; on Settled by rules, Confirm all.
4. **A margin is shown as numbers or as the margin-floor bar, never both in the same area.** Sentences next to the bar do not repeat its numbers.
5. **Colour has one job each.** Blue means "you can click this": no blue status words, percentages or amounts. Terracotta is below floor and money lost. Amber is "needs a person". Good or neutral results are plain text; negative amounts are plain text with a minus sign.
6. **Costliest first.** Rows with nothing to act on collapse behind "Show {n} unaffected".
7. **The same thing is counted the same way everywhere.** Home's "7 won orders will absorb $1,682" is the same count as Leakage's "13 won orders still to buy. 7 absorb increases".
8. **Plain names, not internal ones.** No `MAT-EPDM-70` or `E07` in sentences; no builder's column names ("Cards", "Above", "Overpaid").
9. **A column with the same value in every visible row is hidden** and said once above the table ("Recommended for every one shown: call the customer first").
10. **Demo controls live behind "Open demo controls"** at the foot of the sidebar.
11. **Sentence case everywhere.**

## Colors

Slate neutrals, one blue for everything clickable, and two meaning colours. Tokens are `--color-*` custom properties in `frontend/src/index.css`.

### Neutral
- **Ground** (`#1E2227`): page background and inset boxes.
- **Sheet** (`#262B31`): sidebar, tables, panels, tiles. **Sheet Raised** (`#2E353D`): the selected row.
- **Nav Active** (`#313945`): the active sidebar item and any selected segment or menu choice.
- **Rule** (`#363C44`) for borders, **Rule Soft** (`#30363D`) for row dividers and bar tracks, **Rule Bright** (`#4A525C`) for outline buttons and inputs.
- **Ink** (`#DDE1E6`) for text, **Ink Dim** (`#9EA7B3`) for everything secondary.

### Meaning
- **Go** (`#8FB4E0`): clickable, and only that. The one filled button on a screen (text in Ground) and every link. **Go Soft** (`#B4CCEA`) is its hover and the active nav text.
- **Stop** (`#E5A08C`, terracotta): below the floor and money lost.
- **Attn** (`#D9B777`, amber): needs a person.

Legacy token names (`ink-bright`, `claude`, the material families) remain in `index.css` only as aliases of the palette above, so no element can render in an old colour. They are not colour roles; material families are plain text.

## Typography

**Inter** 400/500/600/700 for all text and for numbers inside tables. **Archivo Narrow 600** with tabular numerals for display figures only, through the shared `FIGURE` class in `MarginBar.tsx`. Both self-hosted with `@fontsource`.

| Role | Face | Size | Use |
|---|---|---|---|
| Page title | Inter 700 | 24–28px | Page h1, matching the sidebar label |
| Panel title | Inter 700 | 20px | Detail panel and report lead |
| Section title | Inter 600 | 16px | "Needs you", "By customer" |
| Body | Inter 400 | 14px | Text and table cells |
| Secondary | Inter 400 | 13px | Sub-lines, captions, table headers |
| Group label | Inter 400 | 12px | Sidebar groups, chart axes |
| Figure | Archivo Narrow 600 | 28–34px | Home counts and leaked figure, panel At risk, report leads |

Tabular numerals apply to figures and right-aligned table cells, not the whole body: Inter's tabular feature also widens the hyphen, which spaced out ids like Q-2026-0101.

## Layout

- **Shell:** the 230px sidebar on the left (sticky, full height), content to the right with a 28px gutter. On narrow screens the sidebar stacks above the content as a grid of its groups.
- **Home:** a single centred column, 760px wide.
- **To decide:** the table (about 60%) and the detail panel (about 40%) side by side; the panel is sticky and stacks below the table on narrow screens.
- **Quote check and Imports:** a form or mapping column on the left, the live result on the right.
- **Leakage:** two tabs, Orders still to buy and Already leaked, one table each.
- **Tables** sit in a Sheet panel that scrolls sideways inside itself on a phone; the page never does.

## Shapes and depth

Corners: 6px on controls, 8px on panels and tables, 10px on tiles. Depth is tonal (Ground, Sheet, Sheet Raised) and ruled; the only shadows are on popovers and the demo drawer.

## Components

### Buttons
- **Primary:** Go fill, Ground text, 44px tall, sentence case. One per screen.
- **Outline:** Sheet fill, Rule Bright border, Ink text. Everything that is not the one primary action.
- **Small:** 13px, for row actions ("Confirm 17", "Buy now", "Undo").

### Sidebar
Wordmark "Margin Guard", Home on top, then four groups with 12px Ink Dim labels. Items are 9px 10px; the active one is Nav Active with Go Soft text. Counts only on To decide and Settled by rules. Footer: a dashed box, "Sample shop, synthetic data." and the "Open demo controls" link, plus "Agents working…" only while the agents run.

### Demo-controls drawer
A right-hand drawer over a dimmed page: shop date and model, "Send a test supplier email", and the agents' activity. Escape or a click outside closes it.

### Table row and detail panel (To decide)
Rows: Customer (name, then quote id and value dim), Margin now (percent, then "1.1 pts under floor" in terracotta), Recommended, At risk (right, semibold). The selected row is Sheet Raised; J and K move the selection. Supplier questions are rows at the top with "Answer a question" in amber. The panel: name and quote, one sentence, the margin-floor bar with At risk beside it, the cost lines, Approve with "Choose another action" and "Reject" under it, then four collapsed sections.

### Margin-floor bar (signature)
A 6px track: terracotta below the floor, Rule Bright above it. A floor tick labelled "Floor 23.7%" underneath; a hollow dot for the quoted margin and an arrow to the margin now, labelled "Quoted 25.2%" and "Now 22.6%" on the bar (Now in terracotta when under the floor). The scale is fitted to the three values with room either side, so labels run outward and never collide. It appears in three places only: the To decide panel, the Quote check verdict and a Leakage job's trace. Never in list rows.

### Cost-moved line
One format everywhere: material, old price, arrow, new price per unit, effective date. "FKM 75, $14.80 → $15.76/lb, Dec 1". This is the only place an arrow appears.

### Tiles (Home)
Sheet, 10px corners, 20px padding; title and dim sub-line at the top, figure at the bottom left.

### Segmented control and popovers
Segments: a Rule Bright outline, the selected segment in Nav Active with Go Soft text (never amber). Popovers (Filter, What if) open under an outline button and close on outside click or Escape.

## Do's and Don'ts

### Do
- **Do** keep it dark only, in the slate palette.
- **Do** use blue only for what can be clicked, terracotta only for below floor or money lost, amber only for "needs a person".
- **Do** keep one filled button per screen.
- **Do** write cost moves in the one format, and name materials and suppliers the way people say them.
- **Do** say a repeated column value once, above the table, and collapse rows with nothing to act on.
- **Do** count the same thing the same way on every page.

### Don't
- **Don't** bring back the green navigation band, uppercase stencil labels, pill badges, coloured material squares or middle-dot strings.
- **Don't** put the margin-floor bar in list rows, or show the bar and the same margin numbers together.
- **Don't** use blue for status words, percentages or amounts.
- **Don't** put demo or simulation controls in the working layout.
- **Don't** add a light theme.
