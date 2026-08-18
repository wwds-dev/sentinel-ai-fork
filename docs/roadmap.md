# Roadmap — Sentinel, Atelier, SONAR

Written 2026-08-12, after the fork. This is the index; each item links to the
plan that already covers it in detail.

## Where things stand

| repo | state |
|---|---|
| **sentinel_ai** | `main.py` 9,034 lines (was 11,902). Refactor phases 1–2 done. TODO #1, #3, #4, #5, #6 closed; #2 in progress. 12 agents in the sidebar. |
| **atelier** | Forked with full history (21 commits). **Nothing stripped** — still a copy of Sentinel. |
| **sonar** | Sports tab shipped: NFL props with real odds arithmetic, 33 tests, 266 passing overall. |

## The one thing blocking everything else

**Sentinel refactor phase 3 → phase 4.**

Phase 4 turns each agent into a self-contained module. That module is the unit
that Atelier deletes, that the platform package leaves behind, and that a future
split moves. Doing any of those before phase 4 means doing the same untangling
two or three times.

Phase 3 carries the one open design decision: **composition over mixins**
(`docs/refactor_plan.md`). Settle it before writing the `AgentHost` protocol.

## Do now — independent of the blocker

These need nothing from the refactor and can land in any order.

1. ~~**Remove `nfl_bet` from Sentinel.**~~ **DONE (2026-08-12).** 20 methods
   and 549 lines out of `main.py` (9,584 → 9,008), plus both agent modules, the
   docs page, the test class, the seed entry and the DB row. SONAR owns sports
   betting now. Sidebar: 13 agents → 12.

2. **GUI step 1 — type scale: DONE (2026-08-12).** `ui/style.py` went from
   five sizes (10/11/12/13/22) to three (11 caption · 13 body · 22 display) and
   from six weights (400/500/600/700/800/bold) to two (400/500). The scale is
   documented at the top of the sheet, including the 15px title role the
   section renderer will use.

   **GUI step 2 — right-rail figures: DONE (2026-08-12).** New `Meter` and
   `Bar` widgets in `ui/widgets.py` (painted, not styled — a QProgressBar would
   inherit the sheet's audiobook-progress look). SYSTEM shows RAM/CPU/SWAP/BATT
   as bars, BUDGET shows session and daily spend, all with level colouring that
   escalates green → yellow → red at 60% and 90%. Exact figures moved to
   tooltips rather than crowding the glanceable number. Budget bars fill with
   what is *spent*, not what is left — a bar that empties as you spend reads as
   progress towards something good.

   **Next: GUI steps 3–4** (run bar, section renderer) — both restructure panel
   layout, so they are cheaper after refactor phase 4.

3. **Commit the working trees.** Sentinel has 11 uncommitted paths and SONAR 6,
   including this session's deletions and the whole sports feature. They are
   green but unsaved.

## Then — the critical path

4. **Refactor phase 3** — `AgentHost` protocol + `AgentPanel` base. Also absorbs
   the 16 near-identical `*_load_models` methods.
5. **Refactor phase 4** — move verticals to `ui/panels/`, smallest first
   (osint 227 → author 1,195).
6. **Extract the platform package** — provider clients, `api_limits`,
   `usage_tracker`, `validator`, `registry`, `run_logger`, `database`,
   `runtime_paths`, the request guard, and `ui/{style,widgets,workers,dialogs}`.
   Sentinel consumes it first; nothing moves between apps yet.
7. **Refactor phase 5** — `GodAI` becomes a shell.

## Then — Atelier

8. **Atelier takes the platform package**, then deletes its six non-creative
   verticals and `providers/` (`atelier/FORK_PLAN.md`).
9. **Re-shape Atelier as tabs**: Write · Audio · Web · Gigs.
10. **Rebrand** — app name, bundle id, icon, and the two traps that bite if it
    is incomplete: `runtime_paths.APP_NAME` (shared Application Support
    directory) and `SINGLE_INSTANCE_KEY` (launching Atelier focuses Sentinel).
11. **Lab Hub launchpad entry** for Atelier.

## Optional, whenever

- **Chat Projects stage 2** (`docs/projects_roadmap.md`) — instructions,
  defaults and per-project budget. Stage 1 (filter + rename) shipped. Worth it
  only if the goal is "stop re-establishing context", not a tidier list.
- **More sports in SONAR** — the registry is the extension point; a second sport
  is a `Sport(...)` entry plus its prop types.
- **`chat` in Atelier** — decide whether a creative app wants its own general
  assistant, or none.

## What this leaves Sentinel as

After #1 and Atelier's split: `chat` · `osint` · `osint_heavy` · `wifi` ·
`bug_bounty` · `manager` — six agents, one sentence to explain, and a sidebar
that fits without scrolling. That is the point of the whole exercise.

## Sequencing note

Steps 1–3 are safe today and independent. Steps 4–7 want a clear run — they are
one continuous piece of work, and stopping halfway leaves `main.py` in a state
where half the panels are modules and half are not. Steps 8–11 are mechanical
once 4–7 are done.
