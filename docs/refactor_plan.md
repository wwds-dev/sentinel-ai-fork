# Splitting `main.py` — plan

`main.py` is 11,902 lines. `GodAI` alone holds 387 methods. This is the plan for
TODO.md #2, written before moving any code.

## What is actually in there

Measured, not estimated:

| region | methods | lines |
|---|---:|---:|
| 15 agent verticals (panel + runners + callbacks + parsing) | ~225 | 6,280 |
| shared core (chrome, styling, dialogs, request guard, workers) | ~160 | 5,389 |

Largest verticals: author 1,195 · manuscript 911 · nfl_bet 480 · wifi 477 ·
ops_identity 436 · fiverr 435 · osint_heavy 434 · bug_bounty 386 · music 339 ·
health 308 · webdesign 293 · manager 245 · osint 227.

Largest single methods: `build_author_panel` 556 · `build_center_panel` 328 ·
`apply_global_style` 312 · `build_right_panel` 300 · `show_model_guide` 269 ·
`_seed_tooltips` 244.

## The finding that makes this tractable

Each agent vertical was checked for how many `self.*` attributes it uses that it
does not own:

| vertical | attrs used | not owned |
|---|---:|---:|
| author | 135 | 27 (20%) |
| osint | 87 | 23 (26%) |
| music | 51 | 16 (31%) |

The verticals are ~75% self-contained, and the external references are almost
the *same set every time*:

- provider clients — `ollama` `openai` `deepseek` `kimi` `gemini` `anthropic` `qwen`
- the request guard — `authorize_request` `record_request` `abandon_request`
  `note_request_usage` (added for TODO #1)
- `run_backend` · `agent_instances` · `_note_failure` · `show_agent_docs` ·
  `execution_mode_box`

That is a ~15-member interface, not a tangle. Panels can be extracted against it
without rewriting their internals.

## Target layout

```
main.py                 # entry point + GodAI shell only  (~800 lines)
ui/
  workers.py            # ChatWorker, SubprocessWorker, ModelPullWorker,
                        #   FiverrImageWorker, ShortsWorker           (~200)
  widgets.py            # FlowLayout, CollapsibleSection              (~170)
  style.py              # apply_global_style + the panel stylesheets  (~570)
  tooltips.py           # _seed_tooltips data                         (~245)
  dialogs.py            # show_settings, show_model_guide, show_cost_history,
                        #   show_run_log                              (~930)
  host.py               # AgentHost protocol — the ~15 shared members
  book_widgets.py       # already exists
  panels/
    base.py             # AgentPanel: provider/model row, model loading,
                        #   run/stop wiring, the FlowLayout control row
    osint.py  osint_heavy.py  wifi.py  vpn.py  bug_bounty.py
    manager.py  chat.py
```

`services/` keeps all non-UI logic, as it does today.

## Order of work

Each phase ends green: `pytest tests/` plus the offscreen build check
(`QT_QPA_PLATFORM=offscreen` constructing `GodAI()`), which catches import and
layout breakage without a display.

**Phase 1 — lift out what barely touches `self`. DONE (2026-08-12).**

| module | lines | contents |
|---|---:|---|
| `ui/workers.py` | 212 | ChatWorker, SubprocessWorker, ModelPullWorker, FiverrImageWorker, ShortsWorker |
| `ui/widgets.py` | 161 | FlowLayout, CollapsibleSection |
| `ui/style.py` | 315 | `GLOBAL_STYLESHEET` |
| `ui/tooltips.py` | 252 | `seed_tooltips(app)` |

`main.py` 11,902 → **11,007** lines. Verbatim moves: the tooltip body is
unchanged apart from the receiver being named `app`, so its section comments and
application order are preserved.

Verified beyond "it imports": the stylesheet is applied at runtime (9,579 chars,
accent `#3cff88` present) and tooltips are present on `send_btn`, `estimate_btn`,
`allow_kimi_checkbox` and the sidebar agent buttons. 219 tests green, offscreen
`GodAI()` builds.

One trap worth repeating for later phases: rewriting `self` → `app` with
`\bself\.` misses bare `self` in `hasattr(self, ...)`, which fails only at
runtime, not at import. The offscreen build check caught it; a compile check
would not have.

**Phase 2 — extract the dialogs. DONE (2026-08-12).**

| module | lines | contents |
|---|---:|---|
| `ui/dialogs.py` | 735 | `show_cost_history` 144 · `show_run_log` 92 · `show_settings` 203 · `show_model_guide` 269 |

A net **−696** lines in `main.py`. Each moved body is byte-identical to
the original after `self`→`app` and one dedent — verified by diffing the
transformed original against the extracted function, not by eye. `GodAI` keeps
four three-line wrappers so every call site and the Docs/Settings buttons are
untouched.

The dependency surface turned out to be small: `show_cost_history` needs only
`usage_tracker`, `show_run_log` only `run_logger`, `show_settings` seven members,
`show_model_guide` six — plus `app` as the dialog parent.

Two traps, both runtime-only:

- The `hasattr(self, …)` trap from Phase 1 recurred — 6 occurrences here. Fixed
  by rewriting `\bself\b` rather than `\bself\.`.
- **Missing imports do not fail at import time.** The moved bodies referenced
  five provider wrappers plus `Registry` and `Validator`; `ui/dialogs.py`
  imported and compiled cleanly, and only `show_model_guide` raised
  `NameError` when actually opened. Guessing the import list from a regex is not
  enough — walk the AST for `Load`ed names not bound in the module, which found
  all seven at once.

Check used, beyond constructing `GodAI`: stub `QDialog.exec`, open all four
dialogs, and assert on their contents (provider names and key status in the
model guide, non-empty cost history, populated Settings fields).

**Phase 3 — define `AgentHost` and the `AgentPanel` base. DONE (2026-08-20).**

| module | lines | contents |
|---|---:|---|
| `ui/host.py` | 90 | `AgentHost` protocol — the ~15 members a panel may assume |
| `ui/panels/base.py` | 215 | `PROVIDERS`, `flow_row`, `build_provider_row`, `AgentPanel` |
| `tests/test_ui_panels.py` | 437 | 77 tests — the shared row, the loader registry, `AgentPanel` |

**Composition, not mixins** — the decision below is settled. `AgentPanel` holds
its host behind the protocol instead of sharing a namespace with it, which is
why its 20 tests construct a panel against a 42-line `FakeHost` with no `GodAI`
and no window anywhere in the fixture.

`main.py` 5,520 → **5,378** lines. Small by design: no vertical moved. What
changed is that the duplication the verticals *would have carried with them* is
gone first —

- Seven copies of the provider list → `PROVIDERS`.
- Six panels building the same provider combo + model combo + reload wiring →
  one `build_provider_row` call each (10 lines → 2).
- Six `*_load_models` methods → `GodAI.load_models_into`. They had already
  drifted: three noted a load failure on the model box, one swallowed it in
  silence, and two went through a shared helper that swallowed it too. Noting
  it is now the single behaviour.
- `AGENT_MODEL_LOADERS`, a map of *method names* resolved with `getattr`, →
  `register_model_loader` / `load_models_for`. Panels register while they build,
  so a renamed method cannot leave a stale string behind.

The trap this phase, again runtime-only and again invisible to a compile check:
**an unparented row container takes its widgets with it.** `build_provider_row`
adds the combos to a layout, and the layout's container owns them; the first
`AgentPanel` fixture let that container fall out of scope and every later access
raised `RuntimeError: Internal C++ object (QComboBox) already deleted` — from a
line that had nothing to do with ownership. `flow_row(parent)` now takes a
parent, and `AgentPanel.flow_row()` passes itself.

Verified beyond the suite: every panel's row rebuilt in the same order it had
before (labels present for Trace, Bloodhound, Bug Spray and Forge, absent for
Beacon and Tunnel, action buttons after them), and all six panels still land on
their recommended provider *and* recommended model at startup — which only works
if the recommendation system found each panel's loader through the new registry.
Two mutants confirmed the tests bite: dropping the initial `load()` and making
`register_model_loader` a no-op fail 3 and 13 tests respectively.

**Phase 4 — move agent verticals one at a time, smallest first. DONE.**
Bundled into the `chore: initialize Sentinel AI fork` commit (2026-08-22) that
split this project's history out of Sentinel AI: all six verticals — osint,
manager, bug_bounty, osint_heavy, vpn, wifi — landed in `ui/panels/`, each its
own module against the `AgentHost` protocol and `AgentPanel` base Phase 3
defined. `main.py` 5,378 → 3,567 in that commit. Not a clean phase-only number:
the same commit also reshaped `services/registry.py`, `services/pricing.py`
and `services/model_router.py` as part of establishing this as its own project,
so the drop reflects more than the panel move alone. `main.py` has since grown
to 4,082 lines (Trace Live Research work, tracked in TODO.md) — expected, since
the phase was a one-time structural move, not a ceiling.

Not resolved by this phase: `_pending_requests` stayed keyed by agent name.
Moving the panels didn't touch `authorize_request` / `record_request` /
`abandon_request`, which still live on `GodAI` in `main.py`. **Since fixed** —
see Risks below and TODO.md.

**Phase 5 — `GodAI` becomes a shell**: build the three panes, own the shared
services, hold the panel instances. Not started.

## The decision phase 3 settled

**Mixins or composition — composition, decided 2026-08-20.** Mixins
(`class GodAI(QWidget, OsintPanelMixin, …)`) would have been a verbatim
cut-and-paste with no call-site edits — fast, and the file would have shrunk
immediately, but every panel would still share one namespace, so the coupling
would be unchanged and name collisions would stay possible. Composition (each panel a real
`AgentPanel` holding its own widgets, talking to the host through the protocol)
is the actual fix and is what makes panels testable in isolation.

The coupling numbers above said the cost was affordable, and mixins would have
left #2 half-done while looking finished. `AgentPanel` is the composition side of
that: panels hold a host, not a shared namespace.

**Phases 1–3 are complete**: **−1,733 lines** out of `main.py` (895 in Phase 1,
696 in Phase 2, 142 in Phase 3) — the first two structural, the third the design
commitment.

Measure the phase delta, not the file total. The absolute count drifts up while
other work lands and down when agents are cut — `main.py` read 10,391 at the
Phase 2 commit and 5,520 before Phase 3 started, and neither number says anything
about the split.

Phases 4–5 are the remaining move and want a clear run.

## Risks

- **Thin UI test coverage.** `test_ui_panels.py` (phase 3) covers the shared
  provider/model row, the loader registry and `AgentPanel` — but nothing else
  about layout. The offscreen `GodAI()` build is still the only automated check
  that a panel *as a whole* constructs, so run the suite after every move.
- **`_pending_requests` keyed by agent name** (TODO #1) — **resolved.** It is
  now keyed by a `request_id` (`uuid4().hex`) generated in `authorize_request`,
  with a fallback to the agent name when no id is passed. Verified by
  `tests/test_request_guard.py::test_same_agent_runs_can_finish_out_of_order`.
- **Do not renumber during a move.** Moving a vertical and editing it in the
  same commit makes a regression impossible to bisect. Move verbatim, commit,
  then clean up.
