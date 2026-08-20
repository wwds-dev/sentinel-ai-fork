# Handoff — what a fresh session needs to know

Written 2026-08-20 at the end of a long session. Everything below is on disk;
this file exists so the reasoning is not lost with the conversation.

## The one technique that changed the work

**You can render the app to a PNG and look at it, without a display.**

```python
QT_QPA_PLATFORM=offscreen python -c "
import sys, importlib.util; sys.path.insert(0,'.')
sys.argv=['main.py']
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
app = QApplication([])
spec = importlib.util.spec_from_file_location('__m__','main.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
w = m.GodAI()
w.setAttribute(Qt.WA_DontShowOnScreen, True)   # lets it lay out at any size
w.show(); w.resize(1600, 1000)
for _ in range(5):
    w.layout().activate(); app.processEvents()
w.grab().save('/tmp/app.png')
"
```

`WA_DontShowOnScreen` is the important part — without it the offscreen platform
clamps the window to ~800px and every screenshot shows a crushed layout that is
not what the user sees.

Half a dozen design changes were reported as done, on the strength of
`py_compile` passing and a `grep` finding the rule in the source, and none of
them were reaching the screen. Render and look before saying a visual change
works.

## Three bugs that all passed "it compiles"

- **`str.replace` with a missing anchor is a silent no-op.** Three stylesheet
  blocks were appended against anchors that did not exist (one of them was text
  a previous failed insertion was supposed to have added). The file compiled
  every time. Verify the text landed, not that the file still parses.
- **A plain `QWidget` ignores a stylesheet `background-color`** unless it is
  given `setAttribute(Qt.WA_StyledBackground, True)`. This is why the run bar
  had no surface and its controls appeared to float.
- **Panels can carry their own `setStyleSheet`, which beats the global sheet.**
  `build_right_panel` does. Editing `ui/style.py` and seeing no change usually
  means a local sheet is winning.

## Never match agent names as bare substrings

Two near-misses, one of which shipped briefly:

- deleting methods matching `author` removed **`authorize_request`** — the whole
  budget/spend/history guard. It compiled and the UI built; 24 test failures
  caught it.
- searching for `nfl` matched "i**nfl**uences" in the music agent's copy.

Anchor on word boundaries, and diff the symbol list before and after.

## Where the design lives

- Mock screens (approved): https://claude.ai/code/artifact/01436356-bbb0-444c-bf75-8e8ee06127d1
- Direction and the measurements behind it: `docs/gui_redesign.md`
- Type scale, palette and spacing are documented at the top of `ui/style.py`.

## State at handoff

`main.py` 11,902 → ~5,200 lines. Six agents: chat · Trace · Bloodhound · Beacon
· Bug Spray · Forge (a `Tunnel`/VPN entry appeared from another session). 114
tests green.

**Uncommitted:** `sentinel_ai` has 8 paths, `create_and_publish` 24, `bug_spray`
10, and `playmaker` has no commits at all. `sonar` and `lab_hub` are clean. The
new top-level projects came from elsewhere and were not reviewed here.

## What was next

From `docs/roadmap.md` and `TODO.md` #7, in order:

1. Refactor phase 3 — `AgentHost` protocol + `AgentPanel` base. `ui/host.py` is
   already written; nothing consumes it yet. Carries one open decision:
   **composition over mixins** (recommended, see `docs/refactor_plan.md`).
2. Section renderer for the remaining agents. Bloodhound is nearly free —
   `_parse_osint_heavy_sections` exists. Beacon, Bug Spray and Forge need a
   parser each.
3. Extract the shared platform package before the hubs diverge — provider
   clients, request guard, budget/usage/registry, `ui/{style,widgets,workers,dialogs}`.
   Four apps with four copies of the money logic is TODO #1 repeated four times.
