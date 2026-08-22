# Which agents stay in Sentinel, and what becomes its own app

## The seam is already visible in `services/`

This is not a matter of taste. Look at what each group of agents drags along:

| group | dedicated services it owns |
|---|---|
| creative / publishing | `narrator/`, `book_exporter`, `kdp_csv_parser`, `publishdrive_client`, `quote_graphics`, `shorts_generator`, `content_calendar`, `course/` |
| security / intel | `providers/` (username, domain, email lookup, result normalizer) |
| everything else | — |

Eight domain services exist purely to serve author, manuscript, music,
audiobook and fiverr. That is an application's worth of code living inside a
security tool because it happened to be built there. The split is not being
imposed on the codebase; it is being read off it.

There is precedent too: `roi` and `investment` already left for SONAR, and
`_seed_default_agents` carries a comment warning not to resurrect them.

## Proposed homes

### Sentinel — security and intelligence
`chat` · `osint` · `osint_heavy` · `wifi` · `bug_bounty` · `manager`

This is Sentinel's actual identity: reconnaissance, investigation, vulnerability
triage. `chat` stays as the general-purpose assistant every home app wants.
`manager` (builds new agents and tools) stays because it operates on the
registry, which is platform-level.

Keeps `providers/` and the OSINT lookup layer.

### Atelier (new) — creative and publishing
`author` · `manuscript` · `music` · `webdesign` · `audiobook` · `fiverr`

Takes all eight creative services with it. This is the largest group by code
(author 1,195 lines + manuscript 911 alone) and the one with the least in common
with the rest — writing a novel and scanning wifi share nothing but a model
picker.

`fiverr` goes here rather than to a finance app: its output is gig copy, logo
prompts and delivery notes. It is a creative tool that happens to earn money.

**Atelier groups its tools as tabs, not as a sidebar.** Lab Hub already uses
this shape (Apps / Convert Files / Prepare Images / Settings), so it is the
established pattern in this workspace rather than a new invention:

```
Atelier
├── Write      author · manuscript
├── Audio      audiobook · music
├── Web        webdesign
└── Gigs       fiverr
```

Why tabs suit Atelier when a sidebar suits Sentinel:

- **Six tools, not thirteen.** A sidebar earns its keep when the list is long
  enough to need scrolling and grouping; at six it is a column of whitespace.
- **Creative work is long-session and single-task.** You are writing a chapter
  for an hour, not hopping between agents the way an investigation does. Tabs
  make the current context the whole window instead of ceding 230px permanently
  to a switcher you use twice a day.
- **The related tools pair naturally.** author and manuscript are two halves of
  one book pipeline (draft, then publish); audiobook and music are both audio
  production. Tabs express that pairing; a flat sidebar list does not.
- **It reclaims the width the panels need.** AuthorPanel was the widest in the
  app at 1,091px before the FlowLayout work. Dropping the sidebar hands that
  space straight back to the editor.

Sentinel keeps its sidebar: it stays at 6+ agents with genuine category
structure, and investigation genuinely does mean jumping between osint,
osint_heavy and wifi mid-task.

### SONAR (exists) — financial
Already has `roi` and `investment`. **Add `nfl_bet`.**

A betting model is probabilistic wagering against a market — the same shape as
SONAR's paper-trading and market scanning, and nothing like the rest of
Sentinel. It is the one agent whose current placement is clearly wrong.

### Deleted (2026-08-12): `health` and `ops_identity`
Both removed rather than rehomed. 23 methods and 774 lines of panel code came
out of `main.py`, plus `agents/health_agent.py`, two agent docs, the HealthAgent
test class, the `_seed_default_agents` entry and the live `agents` row.

`main.py` 10,311 → **9,584 lines**; the sidebar went from 15 agents to 13.
215 tests green, `GodAI()` builds.

## The precondition — do not skip this

**Extract the shared platform before splitting anything.**

Three apps would each need the six provider clients, the budget/validator logic,
usage tracking, the run logger, the registry and the request guard. Copy those
and they diverge — and the way they diverge is exactly the bug this codebase
just spent a week fixing: TODO #1 existed because one guarded path and twenty
unguarded ones drifted apart inside a *single* app. Three apps triple that
surface.

So: `sentinel_platform/` (or a shared package) holding

- `services/{ollama,openai,deepseek,kimi,gemini,anthropic,qwen}_client.py`
- `api_limits`, `usage_tracker`, `validator`, `registry`, `run_logger`,
  `database`, `runtime_paths`, `history_store`, `model_router`
- the request guard (`authorize_request` / `record_request` / `abandon_request`)
- `ui/` — `style`, `widgets` (FlowLayout), `workers`, `dialogs`

Each home app then contributes only its panels and domain services. One budget
implementation, one cost table, one place to add the next provider.

## Sequencing

1. **Finish the `main.py` refactor** (`docs/refactor_plan.md`, phases 3–5).
   Phase 4 turns each agent into a self-contained module — which is precisely
   the unit that moves to another app. Doing the split first means doing that
   untangling three times instead of once.
2. **Extract the platform package** and have Sentinel consume it. Nothing moves
   between apps yet; Sentinel just stops owning the shared code.
3. **Move `nfl_bet` to SONAR.** One agent, an app that already exists — this is
   the cheap rehearsal that proves the platform package works across repos.
4. **Stand up Atelier** with the six creative agents and their eight services.
5. **Decide `health`. Delete `ops_identity`.**

Steps 1–2 are the real work; 3–5 are mechanical once they are done.

## What this buys

- Sentinel becomes explicable in one sentence again, instead of being a
  launcher with a novel-writing suite inside it.
- Each app's sidebar fits without scrolling — Sentinel drops from 14 agents to
  6, which also makes the GUI work in `docs/gui_redesign.md` easier.
- Lab Hub already exists as the front door for multiple apps, so three focused
  apps fit the workspace's established shape better than one that does everything.

## The honest counterargument

Three apps means three windows, three launches, and three sets of API keys to
keep in step unless the platform package owns key loading too (it should). If
the daily reality is "I open one thing and everything is in it", the split
costs more than it returns. It is worth doing because the *code* is already
three products — not because the workflow demands it.
