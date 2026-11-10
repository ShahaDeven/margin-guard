---
name: Margin Guard
description: An industrial supply catalogue for margin decisions; dense spec tables, figures set tight, every moved cost tabbed by material family.
colors:
  graphite-stock: "#131416"
  sheet: "#1b1d20"
  sheet-raised: "#24262a"
  hairline: "#2e3135"
  hairline-bright: "#474a50"
  paper-ink-bright: "#f1ebdc"
  paper-ink: "#d2cbb9"
  paper-ink-dim: "#a29c8b"
  catalogue-green: "#173b2b"
  catalogue-green-raised: "#1f4a37"
  band-ink: "#e4efe5"
  band-ink-dim: "#a8c4b0"
  go-green: "#5cc48a"
  go-green-hover: "#74d39d"
  index-ochre: "#e3a53c"
  spec-red: "#ef6249"
  claude-violet: "#b7a3f2"
  elastomer-copper: "#b0603a"
  filler-slate: "#a2a8b0"
  metal-steel: "#7ea3d3"
typography:
  display:
    fontFamily: "Archivo Narrow, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 600
    lineHeight: 1
    fontFeature: "tnum"
  headline:
    fontFamily: "Archivo Narrow, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.55
  title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.45
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.625
    fontFeature: "tnum"
  figure:
    fontFamily: "Archivo Narrow, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.45
    fontFeature: "tnum"
  label:
    fontFamily: "Archivo Narrow, Archivo, ui-sans-serif, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    lineHeight: 1.35
    letterSpacing: "0.08em"
rounded:
  tab: "1px"
  sm: "4px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-approve:
    backgroundColor: "{colors.go-green}"
    textColor: "{colors.graphite-stock}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  button-approve-hover:
    backgroundColor: "{colors.go-green-hover}"
  button-outline:
    backgroundColor: "transparent"
    textColor: "{colors.paper-ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "8px 16px"
  button-outline-small:
    textColor: "{colors.paper-ink}"
    rounded: "{rounded.sm}"
    padding: "4px 10px"
  chip-action:
    backgroundColor: "transparent"
    textColor: "{colors.paper-ink-dim}"
    rounded: "{rounded.full}"
    padding: "4px 12px"
  chip-action-selected:
    textColor: "{colors.paper-ink-bright}"
    rounded: "{rounded.full}"
  input-field:
    backgroundColor: "{colors.sheet-raised}"
    textColor: "{colors.paper-ink-bright}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 12px"
  nav-band:
    backgroundColor: "{colors.catalogue-green}"
    textColor: "{colors.band-ink}"
    height: "56px"
  nav-count-active:
    backgroundColor: "{colors.index-ochre}"
    textColor: "{colors.graphite-stock}"
    rounded: "{rounded.sm}"
    padding: "0 6px"
  spec-table:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.paper-ink}"
    rounded: "{rounded.sm}"
---

# Design System: Margin Guard

## Overview

**Creative North Star: "The Estimator's Desk"**

The console is the page an estimator keeps open beside the phone: an industrial supply catalogue printed on graphite stock. Paper-white ink, hairline rules, figures set tight in a condensed face with tabular numerals, and every moved cost tabbed in the colour of its material family. A committed deep catalogue-green band owns the top of every view; below it, the work is ruled spec tables, never a wall of floating cards.

The density is deliberate. A row carries who, what we recommend, which costs moved and by how much, the margin against the floor on one shared scale, and dollars at risk, all readable at a glance down the column. Colour carries a job, never decoration: ochre needs a person, red is below floor or a fault, green is approve or healthy, violet is Claude speaking. Everything else is ink on stock.

The system is dark only; there is no light theme and none should be added. It refuses the category default of grey rounded cards with a single blue accent.

**Key Characteristics:**
- Dark only: graphite stock ground, paper-white ink, hairline rules.
- One committed colour band: catalogue green across the top of every view.
- Role colours with exactly one meaning each; material-family tabs as catalogue thumb-index.
- Archivo for reading, Archivo Narrow for labels and figures; tabular numerals everywhere.
- Squared corners, ruled tables, rows that expand in place.
- Figures name their source; margins share one scale per screen.

## Colors

A warm-paper-on-graphite neutral set, one deep green band, four role colours and three material-family tabs. Tokens live as `--color-*` custom properties in `frontend/src/index.css` (`ground`, `sheet`, `ink`, `shell`, `go`, `attn`, `stop`, `claude`, `elastomer`, `filler`, `metal`).

### Primary
- **Catalogue Green** (`catalogue-green`, `--color-shell`): the navigation band at the top of every view. The one area of committed colour; it is the catalogue's cover stock. **Catalogue Green Raised** (`--color-shell-2`) is its lighter step inside the band: the active view's cell, and hover (60%).
- **Band Ink** / **Band Ink Dim** (`--color-shell-ink`, `--color-shell-dim`): green-tinted paper ink used only on the band (inactive nav, shop date, model name).

### Secondary
- **Index Ochre** (`index-ochre`, `--color-attn`): "needs a person". Needs-a-look flags, contract notes, the floor tick and its label on every margin bar, the active nav underline (3px) and active count badge, the what-if selected multiplier, and the focus ring, text selection and caret. Ochre is where the eye should go next.

### Tertiary
- **Go Green** (`go-green`, `--color-go`): approve and healthy. The solid Approve button (the single filled button on a row), above-floor margins, "Agents idle" dot, the Call contact strip. Hover lightens to **Go Green Hover**.
- **Spec Red** (`spec-red`, `--color-stop`): below floor or a fault. Below-floor margin text and arrowhead, the shaded below-floor zone (20% tint), Reject outline, error banners, leakage bars (80%).
- **Claude Violet** (`claude-violet`, `--color-claude`): Claude's own words and status. The "Claude · 87% sure" attribution beside a rationale, the Claude decided-by label in Done, and the breathing "Agents working" dot and text.
- **Material family tabs**: **Elastomer Copper** (`--color-elastomer`), **Filler Slate** (`--color-filler`), **Metal Steel** (`--color-metal`); unknown materials fall back to Paper Ink Dim. Used only as family tabs: the full-height thumb-index strip on queue rows and the small square tab before a material name.

### Neutral
- **Graphite Stock** (`--color-ground`): page ground and text on solid fills.
- **Sheet** (`--color-sheet`): spec-table and section surfaces. **Sheet Raised** (`--color-sheet-2`): inputs, an expanded row (60%), hover rows (40%), and the above-floor track of the margin bar.
- **Hairline** (`--color-rule`): every row and section rule. **Hairline Bright** (`--color-rule-bright`): table header rule, neutral button and chip outlines, kbd keys, scrollbar thumb.
- **Paper Ink Bright** (`--color-ink-bright`): names, headings, the leading figure in a row. **Paper Ink** (`--color-ink`): default body text. **Paper Ink Dim** (`--color-ink-dim`): sources, captions, secondary costs, placeholders.

### Named Rules

**The One Job Per Colour Rule.** Ochre needs a person, red is below floor or a fault, green is approve or healthy, violet is Claude. No role colour is used for decoration or for a second meaning.

**The Claude Speaks in Violet Rule.** Violet is reserved for Claude's own words and status. A person's edit, a rule decision, key-account chips, selected controls and filter states are neutral ink on hairline.

**The Copper Is Not Ochre Rule.** Elastomer copper is deliberately browner and darker than Index Ochre so a family tab never reads as "needs a person". Family colours never take a role; role colours never mark a family. Where copper tabs sit beside red leak bars (Leakage view) and the two read alike, lighten the bars rather than move copper.

**The Single Band Rule.** Catalogue Green appears in the navigation band and nowhere else as a surface colour.

## Typography

**Body Font:** Archivo (with ui-sans-serif, system-ui, Segoe UI)
**Label/Figure Font:** Archivo Narrow (with Archivo, ui-sans-serif)

**Character:** A grotesque workhorse for sentences, its condensed sibling for everything that is counted or labelled, so figures pack into spec columns the way a parts catalogue sets them. `font-variant-numeric: tabular-nums` is set on the body and inherits everywhere.

### Hierarchy
- **Display** (Archivo Narrow 600, 26px, line-height 1): the four stat-strip figures and view titles ("Needs your decision").
- **Headline** (Archivo Narrow 600, 18px): section titles inside a view ("By material", "Jobs that leaked the most").
- **Title** (Archivo 600, 15px): customer names on rows, stat captions and view subtitles at 15px 400; nav items at 15px 500. Row dollars at risk step up to Archivo Narrow 600, 20px.
- **Body** (Archivo 400, 14px, line-height 1.625): rationales, notes, drafts, banners.
- **Figure** (Archivo Narrow 500, 13px): costs (was → now /lb), quote ids, margin sentences, what-if controls.
- **Label** (Archivo Narrow 600, 12px, 0.06–0.08em tracking, uppercase): table column heads, "at risk", button text (13px, 0.06em), chips, the floor marker, source captions (sentence case, not tracked).

### Named Rules

**The 12px Floor Rule.** No text is set below 12px. Small print is 12px Archivo Narrow; 11px and smaller do not exist in this system.

**The Narrow Counts Rule.** If it is counted, priced, identified or labelled, it is Archivo Narrow with tabular numerals. If it is a sentence a person reads, it is Archivo.

**The Figures Name Their Source Rule.** Every headline figure carries a 12px Paper Ink Dim caption saying where it comes from ("sum of every live card", "56 of 88 jobs since Jan 20").

## Layout

A centred console up to 96rem wide with 16px side padding (24px from 640px). The sticky 56px navigation band spans the full width. Below it a four-figure stat strip, ruled top and bottom with hairline dividers between cells: one column on mobile, two from 640px, four from 1280px.

The Decide view is a 20rem supplier-inbox column beside the queue from 1024px (the inbox drops below the queue on smaller screens). The queue is one ruled spec table with four shared columns from 768px: customer and action, cost that moved, margin vs floor (min 15rem), at risk (7rem). Below 768px a row stacks: customer and dollars on one line, then costs, then the margin bar.

Rhythm: 24px between major blocks and grid gutters, 12–16px inside sections, rows at 14px vertical padding with 24px left inset (clearing the thumb-index tab) and 20px right. Breakpoints are Tailwind's defaults (640 / 768 / 1024 / 1280px).

**The One Scale Rule.** Every margin bar on a screen shares one scale, stated in the column header ("scale 20%–35%"), so bars compare straight down the column.

## Elevation & Depth

Flat. Depth comes from tonal layering (Graphite Stock, Sheet, Sheet Raised) and hairline rules, not shadows. The single shadow in the system is the sticky navigation band's: a 1px dark-green underline plus a soft drop (`0 1px 0 #0e2a1e, 0 6px 18px rgba(0,0,0,0.35)`) so content visibly scrolls under it.

### Named Rules

**The Ruled, Not Lifted Rule.** Sections separate by hairline and tone. Cards, tables and panels carry no shadow; only the sticky band does.

## Shapes

Squared, catalogue-cut corners: 4px (`rounded-sm`, Tailwind 4's 0.25rem) on tables, sections, buttons, inputs, banners, badges and kbd keys. Material swatch tabs are near-square at 1px. Fully round is reserved for action chips and status dots. Lines are 1px hairlines; the active nav underline is 3px ochre; the thumb-index tab is a 6px full-height strip on the row's left edge.

Note: the finish review described the corner as 2px; the shipped build resolves `rounded-sm` and `rounded` to 4px under Tailwind 4. The build is recorded here.

**The Squared Corner Rule.** Corners are 4px everywhere except action chips and status dots (fully round) and family swatches (1px). Nothing in between.

## Components

### Buttons
Squared, condensed caps; the colour of the button is the job it does.
- **Shape:** squared (4px), 1px border.
- **Approve:** the one solid fill on a row. Go Green fill, Graphite Stock text, Archivo Narrow 600 13px uppercase at 0.06em, 8px 16px. Hover lightens to Go Green Hover.
- **Outline tones:** transparent with a role-coloured border at 60–70% and role-coloured text (Reject in Spec Red, answer-it in Index Ochre); hover adds a 10% tint of the same colour. Neutral outline uses Hairline Bright border and Paper Ink text, brightening on hover.
- **Small:** 4px 10px, 12px text.
- **Focus:** global 2px Index Ochre outline, 2px offset. Disabled at 40% opacity.

### Chips
- **Action chips** (choose honor / absorb / reprice / contact): fully round, 1px Hairline border, Paper Ink Dim 12px text. Selected: Paper Ink border, 10% ink tint, Paper Ink Bright text. Selection is neutral, never violet.
- **Status chips:** squared, 1px border, Archivo Narrow 12px uppercase. Key account is neutral (Hairline Bright / Paper Ink); contract note and needs-a-look are ochre.

### Spec Tables / Containers
- **Corner Style:** 4px.
- **Background:** Sheet on Graphite Stock; expanded rows Sheet Raised at 60%.
- **Shadow Strategy:** none (see Elevation).
- **Border:** 1px Hairline; header rule Hairline Bright; rows divided by Hairline top rules.
- **Internal Padding:** 16–20px sections, 14px 20px 14px 24px rows.
- **Notes inside rows** (restated, contract note, call strip): 4px, 1px border at 30% of the role colour with a 4% tint fill, Archivo Narrow 12px uppercase lead-in.

### Inputs / Fields
- **Style:** 1px Hairline border, Sheet Raised fill, 4px corners, 8px 12px, 14px Archivo.
- **Focus:** border shifts to Index Ochre at 70% (draft fields) or Hairline Bright (note field); caret is Index Ochre; placeholder is Paper Ink Dim.

### Navigation
- **Band:** 56px sticky Catalogue Green band, full width. Wordmark in Archivo Narrow 700 at 19px (17px mobile), 0.12em tracking, "MARGIN" in Band Ink and "GUARD" in Index Ochre.
- **Views:** Decide / Settled by rules / Done / Leakage / Data at 15px 500 with a count badge (Archivo Narrow 600 12px, squared). Active: Catalogue Green Raised cell, Band Ink text, Index Ochre 3px bottom bar and an ochre badge with Graphite Stock text. Inactive: Band Ink Dim text, badge on a 30% graphite tint; hover takes the raised green at 60%.
- **Right side:** shop date and model in 13px Band Ink Dim; agent status pill with a 6px dot (Go Green idle, breathing Claude Violet when working).
- **Mobile:** short view labels, horizontally scrolling view strip with the scrollbar hidden.

### Margin Bar (signature)
The margin as quoted, now, and the floor, on the screen's shared scale. A 10px track: everything left of the floor is a 20% Spec Red below-floor zone, right of it Sheet Raised. A 2px Index Ochre floor tick extends past the track, labelled "FLOOR" above in 12px ochre caps. A hollow Paper Ink ring marks quoted; a solid arrowhead marks now (red below floor, green above), joined by a 2px line. Above: "Quoted 25.2% → now 22.6%". Below, the meaning in words: "1.1 pts below the 23.7% floor · was 1.5 pts above". The sentence carries the meaning; the bar illustrates it.

### Queue Row with Thumb-Index Tab (signature)
One row of the Decide spec table, never a boxed card. A 6px full-height tab in the moved material's family colour on the left edge, then the four shared columns. The row is a single button that expands in place (Sheet Raised at 60%) to show Claude's rationale, the lines table, action chips, draft and Approve / Reject. J/K focus mode outlines the worked row with a 2px inset Index Ochre outline and scrolls it to the top.

### Cost Change Spec
Each moved cost set as a catalogue line in 13px Archivo Narrow: family swatch (10px, 1px corners), material, "$5.10 → $5.62/lb", signed change, "from Nov 1". The triggering cost is Paper Ink Bright with the new price and change in 600; supporting costs are Paper Ink Dim.

### What-If Control
A single ruled strip above the queue: "What if these increases were" then squared toggles (as announced / ×1.25 / ×1.5 / ×2). The selected toggle is ochre; margins, gaps and dollars at risk reflow live and the at-risk caption reads "at risk if ×1.5". Display only; nothing is saved.

## Do's and Don'ts

### Do:
- **Do** keep the system dark only; Graphite Stock (#131416) ground, Paper Ink text, `color-scheme: dark`.
- **Do** give each role colour exactly one meaning: ochre needs a person, red below floor or fault, green approve or healthy, violet Claude.
- **Do** tab every material reference with its family colour (copper elastomer, slate filler, steel metal) and keep copper browner and darker than ochre.
- **Do** set every figure, id, price and label in Archivo Narrow with tabular numerals, and give every headline figure a source caption.
- **Do** put all margin bars on a screen on one shared scale, with Quoted, Now and Floor labelled and the gap stated in points.
- **Do** build lists of decisions as one ruled spec table with shared columns and rows that expand in place.
- **Do** use the 2px Index Ochre focus outline with 2px offset; theme selection (ochre 35%), caret (ochre), scrollbar (Hairline Bright thumb) and details markers.
- **Do** make Approve the only solid-filled button on a row; every other action is a ruled outline in its job's colour.
- **Do** lighten red leak bars, not copper tabs, if the two read alike on the Leakage view.

### Don't:
- **Don't** add a light theme.
- **Don't** use violet for anything Claude did not say or do: not for a person's edit, a rule decision, key-account chips, selected controls or filter states.
- **Don't** box queue rows as separate cards or lift sections with shadows; only the sticky band casts one.
- **Don't** round corners beyond 4px, except action chips and status dots (fully round).
- **Don't** put a "→" glyph on buttons or CTAs; the arrow appears only as data notation (a → b).
- **Don't** place eyebrow or kicker labels above headings.
- **Don't** set text below 12px.
- **Don't** use Catalogue Green as a surface anywhere but the navigation band, or fall back to grey cards with a single blue accent.
