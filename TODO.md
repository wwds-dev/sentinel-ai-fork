# Sentinel AI — TODO

> **Legend** — priority `P0` critical · `P1` high · `P2` normal · `P3` low
> categories `security` `bug` `feature` `performance` `design` `docs` `testing` `infra` `research`
> owner `@me` (needs you — accounts, keys, money, judgement) · `@ai` (Claude can do this)

Full reasoning, measurements and verification notes for each item are kept below
under **Detail** — this checklist is the summary view.

---

## v2 — current

- [x] `P1` `design` `@ai` **Refactor Phase 4** — all six specialist verticals now live in `ui/panels/` behind the shared `AgentPanel` boundary. The separate run-id hardening remains tracked below. See `docs/refactor_plan.md`.
- [x] `P1` `design` `@ai` **Refactor Phase 3** — `AgentHost` (`ui/host.py`) and the `AgentPanel` base (`ui/panels/base.py`), with the design decision settled: composition, not mixins. Six panels' hand-built provider/model rows collapsed to one `build_provider_row` call each, six `*_load_models` methods to one `load_models_into`, and a map of loader *method names* to a registry panels fill in as they build. `main.py` 5,520 → 5,378; 77 new tests, 20 of which construct a panel with no `GodAI` at all.
- [x] `P1` `design` `@ai` **GUI overhaul — section renderer.** Shipped for Trace: `SectionCard`/`SectionView` in `ui/widgets.py`, four tabbed text boxes replaced by cards with per-card copy, raw response collapsed behind a disclosure, and a separate streaming box so tokens still show live before there are sections to render. Reuse for Bloodhound next — its parser already exists.
- [ ] `P2` `design` `@ai` **GUI overhaul — section renderer, remaining agents.** Bloodhound has a parser (`_parse_osint_heavy_sections`); Beacon, Bug Spray and Forge need one each. Original note: The change that justifies the rest, and it needs no new parsing: 12 `_parse_*_sections` methods already structure every answer and 70 text panes render it flat. Build against Trace (smallest vertical), then reuse. See `docs/gui_redesign.md`.
- [x] `P2` `design` `@ai` **GUI overhaul — run bar.** Three stacked control rows → one: tool · command · provider · model · live cost · gear. Execution mode, the six provider permissions and the model tools moved into a popover behind the gear. Splitter minimum dropped 985 → 927px. Deferring this to Phase 4 stopped being the right call once Sentinel was down to six agents and 111 lines of control rows.
- [x] `P3` `design` `@ai` **GUI overhaul — flat agent list.** The sidebar accordion was built for fifteen agents; there are six. Drop `CollapsibleSection` from the sidebar, keep it where panels still use it.
- [x] `P1` `design` `@ai` **GUI overhaul — type and spacing scale.** Five sizes (four of which read as one) → three; six weights → two; documented in `ui/style.py` with the 15px section-title role reserved.
- [x] `P1` `design` `@ai` **GUI overhaul — status rail figures.** `Meter`/`Bar` in `ui/widgets.py` drive system and budget; exact numbers moved to tooltips; budget bars fill with what is spent.
- [ ] `P1` `bug` `@ai` Key `_pending_requests` by run-id rather than agent name. Two simultaneous runs of the same agent would overwrite each other's context; unreachable today only because the panels disable their run button mid-flight.
- [ ] `P2` `bug` `@ai` Remove the dead `ops_identity` sidebar entry — it is listed in `agent_titles` with no agent module or panel behind it
- [ ] `P2` `feature` `@ai` Model Kimi prompt caching in `config/pricing.json`. Cache hits are ~80% off input ($0.19/1M), so estimates for repeated context are currently conservative.
- [ ] `P2` `feature` `@ai` **Chat Projects Stage 2** — turn a group of saved chats into a context bundle (instructions, defaults, optional budget). Tractable now that every paid request has one choke point: two hook points instead of 22. See `docs/projects_roadmap.md`.
- [ ] `P3` `design` `@ai` Budget card: `Session €` and `Daily €` could share a row (~34px), but the two label+field pairs do not fit the sidebar's ~250px inner width without shortening the labels
- [ ] `P3` `testing` `@ai` Switch the budget comparison to `Decimal` — `1.00 - 0.90 == 0.09999999999999998`, so a request estimated at exactly the remaining budget is refused. It fails safe, and the test pins the current behaviour.
- [ ] `P2` `research` `@me` Decide whether `RunLogger` should grow a general `note` method — it is the tidier home for the `_note_failure` warnings if they ever need to be queryable
- [x] `P0` `security` `@ai` Paid API calls bypassed every guardrail outside the chat panel — 22 sites constructed a `ChatWorker` directly. `authorize_request` / `record_request` / `abandon_request` / `note_request_usage` now wrap all 19 previously unguarded sites.
- [x] `P1` `bug` `@ai` Agent panels crushed when the window was narrow — 13 control rows converted to `FlowLayout`; splitter minimum 1460px → 985px
- [x] `P0` `bug` `@ai` No timeouts on any paid cloud client — `services/api_limits.py` (120s, 1 retry) now shared by all five
- [x] `P1` `bug` `@ai` Twelve silent `except: pass` blocks replaced with `_note_failure`, which writes to stderr and attaches the reason as a tooltip
- [x] `P1` `testing` `@ai` Test coverage was inverted — the money logic was the untested part. `test_cost_and_limits.py` (31 tests) and `test_request_guard.py` (30 tests), both mutation-verified.
- [x] `P2` `feature` `@ai` Saved Chats — agent filter above the search box, double-click to rename
- [x] `P1` `feature` `@ai` **Trace Live Research, domain/IP slice** — separate consent-gated WHOIS, DNS, and crt.sh collection with source-by-source activity, partial-result retention, cancellation, zero-cost run logging, and Saved Searches integration.
- [x] `P2` `feature` `@ai` **Trace Live Research, username/email slice** — URLScan requires confirmation; email research offers per-source selection, keeps breach services off by default, disables HIBP without a key, distinguishes skipped services from contacted ones, and preserves partial results. Structure Query remains planning-only.
- [ ] `P2` `feature` `@ai` **Trace Live Research, remaining target types** — evaluate lawful, privacy-preserving sources for people, companies, and phone numbers before exposing any collector. Require source-specific consent and avoid data-broker scraping by default.

### Workspace restructure — see `docs/workspace_structure.md`

- [ ] `P1` `infra` `@ai` **Rename "Sentinel AI" → "Sentinel" everywhere** — window title, bundle name, `runtime_paths.APP_NAME`, `SINGLE_INSTANCE_KEY`, the `/Applications` bundle, the Lab Hub tile, the repo docs. Two traps: `APP_NAME` decides `~/Library/Application Support/<name>/`, so the directory needs migrating or the app looks freshly installed; and two apps sharing `SINGLE_INSTANCE_KEY` means launching one focuses the other.
- [ ] `P1` `infra` `@ai` **Extract the shared platform package** — provider clients, `api_limits`, `usage_tracker`, `validator`, `registry`, `run_logger`, `database`, `runtime_paths`, the request guard, and `ui/{style,widgets,workers,dialogs}`. Four hubs each keeping their own copy is TODO #1 repeated four times. Do this before the hubs diverge further.
- [ ] `P1` `feature` `@ai` **Finish integrating VPN Agent** as a Sentinel agent (`agents/vpn_agent.py` and a `Tunnel` sidebar entry have landed; `vpn_agent/` still exists as a standalone project and a Lab Hub tile).
- [ ] `P2` `infra` `@ai` **Create & Publish** — rebrand the fork (app name, bundle id, icon, `APP_NAME`, single-instance key), integrate `vidforge`, re-shape as tabs (Write · Audio · Web · Gigs), rename `author`→Manuscript and `manuscript`→Publisher internally so the display names and keys stop disagreeing.
- [ ] `P2` `infra` `@ai` **Backup & Sync hub** — a standalone app in Sentinel's shape holding Backup Control Center and git_autosync, both runnable from inside it.
- [ ] `P2` `feature` `@ai` **Lab Hub front desk** — hub tiles that list their contents in a smaller font, and a Tools tab presenting Narrator, Unblock Tracker, Convert and Image tools as tiles.
- [ ] `P2` `research` `@me` **Playmaker and Bug Spray now exist as their own projects**, but the working code lives elsewhere: the betting implementation is `sonar/sports.py` (33 tests) and Bug Spray is also a Sentinel agent. Decide whether each project is the real home or the scaffold gets dropped.
- [ ] `P3` `infra` `@ai` **SONAR — Oracle tab** for long-term investment monitoring, alongside Playmaker.
- [ ] `P3` `feature` `@ai` **More sports in Playmaker** — the `Sport(...)` registry in `sonar/sports.py` is the extension point; a second sport is an entry plus its prop types.

### Interface, remaining from the approved mock screens

- [x] `P2` `design` `@ai` **Trace result renderer** — Trace now uses `SectionView` cards with persistent activity tracking; no result tabs remain in its panel. Bloodhound presentation work is tracked with the remaining-agent renderer item above.
- [ ] `P3` `design` `@ai` The `READY` pill is the last uppercase letter-spaced element in the centre column; the design has no such chrome.
- [ ] `P3` `design` `@ai` **SAVED CHATS is a four-control stack** (filter, search, list, two buttons) in a rail that is otherwise flat rows. Compress it.
- [ ] `P3` `design` `@ai` Normalise the remaining ad-hoc `setContentsMargins` calls onto the 4/8/16/24 scale — the right rail and centre are done, the agent panels are not.

### Process

- [ ] `P2` `docs` `@ai` **Verify visual changes by rendering, not by grepping** — `docs/handoff.md` has the offscreen `WA_DontShowOnScreen` + `grab()` recipe. Several design changes were reported as done while never reaching the screen.
- [ ] `P3` `infra` `@me` `bazaar` and `playmaker` had no initial commit, so `git_autosync` was skipping them entirely. Both now have one. Worth checking no other project is in that state after the restructure.

## v3 — later

- [ ] `P2` `feature` `@ai` Streaming responses in the chat panel, instead of wait-then-dump
- [ ] `P2` `feature` `@ai` Local model provider (Ollama) as a zero-cost fallback when the budget cap is hit
- [ ] `P3` `infra` `@ai` One shared retry-with-backoff wrapper across providers, replacing per-client handling
- [ ] `P3` `feature` `@ai` Export a run — prompt, response, usage, cost — as a single markdown file

---

# Detail

---

## 1. Paid API calls bypass every guardrail outside the chat panel  ⚠️

**22 sites construct a `ChatWorker` directly; there is 1 `validator.validate`
call and 0 usage-tracking calls in the whole app.**

Only `send_prompt()` (the chat panel's Send button) runs the guarded sequence:

    estimate cost → validator.validate (budget) → confirm_external_api_request
    → run_logger.start → ChatWorker → log_request + save_chat + run_logger.finish

Every other runner (`osint_analyse`, `roi_analyse`, `health_analyse`,
`inv_analyse`, `nfl_bet_analyse`, `music_analyse`, `webdesign_generate`,
`wifi_run`, the author/manuscript generators, …) picks a provider that may be a
paid one and calls `ChatWorker` directly. Consequences:

- the €1 session / €5 daily caps do not apply to most of the app;
- "Cost Today" and "Requests Today" stay at 0 no matter what those agents spend;
- no confirmation prompt before spending money;
- nothing is written to Saved Chats (which is why every saved chat is `chat:`).

**Fix:** two helpers on `GodAI`, and every runner calls them —

- `authorize_request(agent, tool, provider, model, prompt) -> bool`
  (estimate → validate → confirm → `run_logger.start`; `False` means blocked)
- `record_request(agent, tool, provider, model, prompt, messages, response, usage)`
  (`log_request` → session totals → `save_chat` → `run_logger.finish`)

This closes four separate defects with one change.

**Status: DONE (2026-08-12).** `authorize_request` / `record_request` /
`abandon_request` / `note_request_usage` live on `GodAI`, and all 19 previously
unguarded `ChatWorker` sites call them — 20 `authorize_request`, 19
`record_request`, 17 `abandon_request`. Verified: all 12 agent panels are
refused when the provider checkbox is off, and a completed run now bills the
session and writes a Saved Chat under its own agent name.

Two things surfaced while wiring it:

- `Registry` reads the **SQLite DB**, not `config/registry.json` (the JSON is
  only a seed via `_migrate_registry`). Both were updated.
- `chat`, `osint` and `manuscript` did not list `anthropic` or `kimi` in
  `allowed_providers`, and no tool listed them either — so picking Anthropic or
  Kimi anywhere was already being rejected as "does not permit provider" before
  any of this. Fixed in the DB and the seed.

Not wired, deliberately: `roi`, `investment` (moved to the SONAR app — see the
comment in `_seed_default_agents`) and `ops_identity`, none of which have an
agent module or panel here. **`ops_identity` is still listed in the sidebar and
`agent_titles` despite having no implementation — a dead menu entry worth
removing.**

Concurrency caveat: `_pending_requests` is keyed by agent name, so two
simultaneous runs of the *same* agent would overwrite each other's context. The
panels disable their run button while a request is in flight, so this is not
reachable today — but keyed-by-run-id would be more robust.

## 2. `main.py` is too big — IN PROGRESS (phases 1–3 of 5 done)

One file holds 17 agent UIs, routing, cost logic, history and styling. The cost
is concrete: a checkbox-spacing fix had to go in the global stylesheet because
the pattern repeats everywhere, and a card-padding fix touched 6 identical
`setContentsMargins` calls. (`list_models()` ×64, `QGroupBox(` ×57,
`setContentsMargins` ×75, `provider_box.addItems` ×13.)

**Fix:** one module per agent panel (`ui/panels/osint.py`, …) plus a shared
`AgentPanel` base for the provider/model/actions row all 17 rebuild by hand.
Do this *after* #1 — the shared helper makes the seam obvious.

**Plan written: `docs/refactor_plan.md`** (2026-08-12). Measured layout, a
five-phase order that ends green at every step, and the finding that makes it
tractable: each agent vertical is ~75% self-contained and the code it reaches
outside itself is the same ~15-member interface every time (provider clients,
the request guard from #1, `run_backend`, `agent_instances`, `_note_failure`).
**Phase 1 is DONE (2026-08-12):** `ui/workers.py` (212), `ui/widgets.py` (161),
`ui/style.py` (315) and `ui/tooltips.py` (252) extracted verbatim; `main.py`
11,902 → 11,007. Verified at runtime, not just by import — the stylesheet is
applied and tooltips are live.

**Phase 2 is DONE (2026-08-12):** the four `show_*` dialogs moved to
`ui/dialogs.py` (735 lines), a net −696 in `main.py`. `GodAI` keeps four
three-line wrappers, so no call site changed. Each body is byte-identical to the
original after `self`→`app` and one dedent — diff-verified rather than eyeballed.

The trap worth carrying into Phase 3: **a missing import does not fail at import
time.** The moved bodies referenced five provider wrappers plus `Registry` and
`Validator`; `ui/dialogs.py` compiled and imported fine, and only
`show_model_guide` raised `NameError` when actually opened. Guessing the import
list from a regex missed all seven; walking the AST for `Load`ed names not bound
in the module found them at once. The check that caught it was stubbing
`QDialog.exec` and opening all four dialogs, asserting on their contents.

**Phase 3 is DONE (2026-08-20):** `ui/host.py` (90) holds the `AgentHost`
protocol and `ui/panels/base.py` (215) the `AgentPanel` base; `tests/test_ui_panels.py`
(77 tests) covers both. The design decision is settled — **composition**, so a
panel holds a host rather than sharing a namespace with it, and 20 of those tests
build a panel against a 42-line fake host with no `GodAI` and no window.

No vertical moved, which is why `main.py` only went 5,520 → 5,378. What went was
the duplication the verticals would otherwise have carried with them: seven copies
of the provider list, six hand-built provider/model rows, six `*_load_models`
methods (which had already drifted — three reported a load failure, three
swallowed it), and `AGENT_MODEL_LOADERS`, a map of method *names* resolved by
`getattr`, now a registry each panel fills in as it builds.

The trap this time, again runtime-only: **an unparented row container takes its
widgets with it.** The combos belong to the container of the layout they are added
to, so a container that falls out of scope leaves every combo raising
`RuntimeError: Internal C++ object already deleted` from lines that have nothing
to do with ownership. `flow_row(parent)` takes a parent now.

**Next: Phase 4** — move the verticals into `ui/panels/`, smallest first, verbatim,
one commit each.

## 3. Other agent panels still crush when the window is narrow

`FlowLayout` (main.py) fixed the chat panel: a `QHBoxLayout` reports the sum of
its children as its minimum width, so a long control row pins an impossible
minimum on the pane and Qt compresses buttons past their own minimums —
labels get chopped to "uto Rout", "ecomme".

**Status: DONE (2026-08-12).** 13 control rows converted to `FlowLayout`:

| panel           | min width before | after |
|-----------------|-----------------:|------:|
| AuthorPanel     | 1091 | 403 |
| WiFiPanel       |  803 | 462 |
| NFLBetPanel     |  728 | 473 |
| OSINTPanel      |  728 | 257 |
| OSINTHeavyPanel |  728 | 503 |
| WebdesignPanel  |  728 | 507 |
| ManuscriptPanel |  711 | 670 |
| BugBountyPanel  |  704 | 573 |

The result that matters: the splitter's minimum width is now **985px, under the
window's own 1000px minimum**, so the three panes fit at the narrowest allowed
window and nothing can be crushed. It was 1460px when this started.

Notes for future conversions:

- Rows come in three shapes and all three needed handling: `addLayout(row)`,
  `addLayout(row, r, c, rs, cs)` into a `QGridLayout`, and `QHBoxLayout(widget)`
  built straight onto a container.
- `FlowLayout.addWidget` now accepts (and ignores) `QBoxLayout`'s stretch and
  alignment arguments, so a `QHBoxLayout` can be swapped in without touching
  call sites — the fiverr panel passes a stretch factor.
- `addStretch()` calls were dropped: a stretch has no meaning once items wrap.

Not converted: the API-key rows (771px). They live inside a scroll area, so
their width no longer drives any pane minimum.

## 4. No timeouts on any cloud client

`ollama_client` sets 10s/300s. All five paid clients — `openai_client`,
`deepseek_client`, `kimi_client`, `gemini_client`, `anthropic_client` — passed
no timeout at all, so a hung connection froze that agent with no recovery.

**Status: DONE (2026-08-12).** `services/api_limits.py` holds the shared values
(120s, 1 retry) and all five clients use them. Verified on the constructed SDK
objects, not just in source; a request to a black-hole address now raises
`APITimeoutError` instead of hanging.

Two notes for whoever tunes this: google-genai's `HttpOptions` takes
**milliseconds** while the other four SDKs take seconds, and the timeout applies
*between streamed chunks* rather than to the whole generation — so 120s does not
cap a slow model.

## 5. Silent `except: pass` blocks

Failures vanished, including around history loading and model listing — if
`load_history_list` threw, the list was silently empty and looked identical to
"you have no saved chats".

**Status: DONE (2026-08-12).** All 12 were replaced with
`except Exception as exc: self._note_failure(...)`. The helper writes
`[warn] <context>: <type>: <message>` to stderr — which the app launcher already
captures in `/tmp/sentinelai_launch.log` — and, where a widget is passed,
attaches the reason to it as a tooltip so an empty model dropdown explains
itself without reading a log.

Covered: the eight `*_load_models` methods, `apply_agent_recommendation`,
`_ops_write_env_key`, `load_history_list` and `closeEvent`. The last two are
still non-fatal on purpose (shutdown, and a key that is already saved in the
database) — they just say so now instead of disappearing.

Verified by injecting a `ConnectionError` into a provider: the failure reaches
stderr and the tooltip, the call does not raise, and the UI survives.

One `except Exception: pass` remains on purpose, inside `_note_failure` itself:
the error reporter must never raise.

`RunLogger` was not used for this — its API is run-scoped (`start`/`finish`/
`cancel`) with no general note method. Adding one would be the tidier home for
these if they ever need to be queryable.

## 6. Test coverage is inverted

The scenario tests cover agent prompt construction, but nothing covered
routing, cost estimation, validation or history — the money logic was the
untested part.

**Status: DONE (2026-08-12).** `tests/test_cost_and_limits.py` adds 31 tests
over the two things that decide whether money is spent and how much:
`Validator` (all ten rules, incl. per-agent/session/daily caps, the paid-provider
checkboxes, and ollama's exemption) and `UsageTracker` token/cost accounting
(each SDK's token naming, exact/estimated/mixed, cost invariants).

They are real tests, not decoration — verified by mutation: deleting the
session-budget check fails `test_request_over_session_budget_is_refused`, and
making the token estimate return zero fails three tests. Both mutations were
reverted and the sources confirmed byte-identical.

Design notes: `Validator` takes its registry by injection, so the gate tests use
a stub and never touch the database. `calculate_cost_eur` does read the pricing
table, so it is asserted on invariants (local is free, unknown backend is free,
cost rises with tokens, never negative) rather than hardcoded prices, which
would break whenever pricing is edited.

`authorize_request` / `record_request` / `abandon_request` are now covered too
— `tests/test_request_guard.py`, 30 tests. It builds `GodAI` once per module
(constructing it costs ~10s, so per-test was 118s and unusable) and swaps the
usage tracker, chat history and run logger for fakes, so no test bills a request
or writes into `data/chats/` — verified by comparing row and file counts either
side of a run.

What it pins is the behaviour where a bug costs money: a blocked or declined
request opens no run, recording without authorising bills nothing, double-record
bills once, and an abandoned request stays unbilled even if a late response
arrives. Mutation-verified — making `record_request` or `abandon_request` leak
their pending context fails the double-billing tests.

Deliberately not duplicated: the ten `Validator` gates and the token/cost maths
stay owned by `test_cost_and_limits.py`. `test_request_guard.py` keeps only three
edge cases that file does not reach, one of which pins a float-precision quirk —
`1.00 - 0.90 == 0.09999999999999998`, so a request estimated at exactly the
remaining budget is refused. It fails safe, and a switch to `Decimal` should
flip it.

## 7. Full GUI overhaul

The colours are right; hierarchy, density and information design are not. Three
measurements rather than opinions: the type scale was five sizes of which four
read as one; **12 `_parse_*_sections` methods** structure every agent's answer
and **70 text panes** then render it flat; and three control rows sit between
you and the input box.

Direction and mock screens: **`docs/gui_redesign.md`** plus the published
mockup (run bar, section-rendered Trace output, narrow-window reflow).

- [x] **Type and spacing scale** — three sizes, two weights, documented in
      `ui/style.py` with the 15px section-title role reserved.
- [x] **Status rail figures** — `Meter`/`Bar` in `ui/widgets.py` driving system
      and budget; exact numbers moved to tooltips.
- [ ] **Flat agent list.** The sidebar accordion existed for fifteen agents;
      there are six. Drop `CollapsibleSection` from the sidebar, keep it where
      panels still use it.
- [ ] **Run bar.** One row — agent · provider/model · live cost · Run — with
      mode, the provider toggles and auto-apply behind a settings affordance.
      Restructures the chat panel, so cheaper after refactor phase 4.
- [ ] **Section renderer.** The one that justifies the rest, and it needs no new
      parsing. Build against Trace (smallest vertical, 227 lines), then reuse
      for the other five agents.

Deliberately not proposed: a new palette (the one part that is not broken), and
a command palette (the sidebar was never the bottleneck — the control rows
were; revisit once the run bar exists).

---

## Smaller items

- Saved Chats: **DONE (2026-08-12)** — agent filter above the search box, and
  double-click to rename. The filter is built from the chats that exist, so it
  only offers agents actually used, and it intersects with the search box rather
  than overriding it. Rename writes the `title` field that
  `chat_title_from_data` already preferred but nothing ever wrote. One pass over
  the files serves both the filter options and the rows, so no extra disk reads.

  Next step is **Chat Projects Stage 2** — see `docs/projects_roadmap.md`. Stage
  1 (this) made the list tidier; Stage 2 turns a group of chats into a context
  bundle (instructions, defaults, optional budget), which is the part that
  earns its keep. It is tractable now because TODO #1 gave every paid request a
  single choke point: project scoping has two hook points instead of 22.
- Kimi prompt caching ($0.19/1M on cache hits, ~80% off input) is not modelled
  in `config/pricing.json`, so estimates for repeated context are conservative.
- `BUDGET` card: `Session €` / `Daily €` could share one row (~34px saved), but
  the two label+field pairs do not fit the sidebar's ~250px inner width without
  shortening the labels.
