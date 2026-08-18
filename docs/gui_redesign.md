# GUI redesign — direction

The colours are right. What is wrong is **hierarchy, density, and the fact that
structure is computed and then thrown away.** Three measurements say it better
than opinion does.

## Diagnosis

**1. There is no type scale.** `ui/style.py` uses `10px · 11px · 12px · 13px ·
22px`. Four of those five are visually identical at normal viewing distance, so
nothing on screen reads as more important than anything else. Every label,
value, heading and hint arrives with the same weight.

**2. Structure is parsed, then discarded.** There are **12 `_parse_*_sections`
methods** that turn each agent's response into labelled sections — and **70
`QTextEdit`/`QTextBrowser` panes** that render the result as flat text. The app
already knows the answer has parts; it just doesn't show them as parts.

**3. The input is buried behind a form.** The chat panel stacks three control
rows (Tool/Command · Provider/Model/Refresh/Guide/Docs · Mode + five provider
checkboxes) before you reach the box you type in. That is a settings dialog
wearing the costume of a workspace.

**4. The right rail states numbers as sentences.** "Used: 11.3 GB · Free: 9.4 GB",
"Session Cost: €0.00". Six cards of small grey text, no figure anywhere, so
nothing can be read at a glance — which is the only thing a status rail is for.

## Direction

### A real type scale — 3 sizes, 2 weights

| role | size | weight |
|---|---:|---:|
| display (agent title) | 22px | 500 |
| title (card + section headings) | 15px | 500 |
| body / control | 13px | 400 |
| caption (units, hints, metadata) | 11px | 400 |

Delete 10px and 12px. Two weights only — 400 and 500. Bold-everything is why
the current UI reads flat.

### One run bar instead of three rows

Collapse the three control rows into a single bar: **agent chip · provider ·
model · live cost · Run**. Everything else — execution mode, the five provider
checkboxes, auto-apply — moves behind one settings affordance on that bar.

Those toggles are set once a week; they currently occupy the most valuable
real estate on the screen, permanently. The cost readout belongs here because
it is the one number that changes with every keystroke and should be visible at
the moment you decide to spend it.

### Render the sections that already exist

This is the highest-value change and it needs no new parsing. Feed the output of
each `_parse_*_sections` into a card list: a heading per section, metrics as
figures, and the raw response collapsed behind a disclosure at the bottom.

The parsers already exist for osint, osint_heavy, health, nfl_bet, roi, author,
music, inv and more. The work is a renderer, not an analysis.

### Figures, not sentences, in the right rail

Memory, swap and budget are all "x of y" — draw them as bars. A budget that is
84% spent should be visible without reading. Keep the numeric value next to the
bar; drop the prose around it.

### One spacing scale

`setContentsMargins` appears 75 times with ad-hoc values. Pick 4 / 8 / 16 / 24
and use nothing else. Most of the "not quite right" feeling in a dense UI is
inconsistent gaps rather than wrong colours.

## Order of work

1. Type scale + spacing scale in `ui/style.py` — one file, immediately visible,
   trivially revertible.
2. Right-rail figures — small, self-contained, high perceived payoff.
3. Run bar — restructures the chat panel only.
4. Section renderer — build it for one agent (osint has the smallest vertical at
   227 lines), then reuse for the other 11.

Steps 1–2 are safe now. Steps 3–4 touch panel structure, so they are cheaper
after the refactor's phase 4, when each panel is its own module.

## Deliberately not proposed

- **A new colour palette.** The greens and greys work; changing them would spend
  goodwill on the one thing that is not broken.
- **A command palette.** Tempting, but the sidebar is not the bottleneck — the
  control rows are. Revisit once the run bar exists.
- **Animation.** Nothing here is slow enough to need it.
