# Chat Projects — Stage 2 roadmap

Stage 1 (a tidier Saved Chats list) is **done**: agent filter, search, and
rename. This document is the plan for Stage 2 — turning a group of chats into a
**context bundle**, which is the part that actually earns its keep.

The distinction matters. Stage 1 makes the list easier to read. Stage 2 means
you stop re-establishing the same context every time you open an agent: a
project carries its own instructions, its default agent/provider/model, and
optionally its own budget.

---

## Why this codebase is well suited to it

Every piece Stage 2 needs already exists and only needs a project-scoped
variant. Nothing here is new machinery:

| Need | What already does it |
|---|---|
| Per-scope system prompt | `config/tool_prompts.json` + `build_tool_messages()` |
| Per-scope budget | `Validator` rule 7 (`get_agent_budget`) — same check, different key |
| Per-scope provider/model defaults | `save_provider_model_preference()` |
| Registry-style config UI | the Settings dialog already edits `agents`/`tools` |
| A single choke point per request | `authorize_request()` / `record_request()` (TODO #1) |

That last row is what makes this tractable now and would not have been before:
every paid request in the app passes through two functions, so project scoping
has exactly two hook points rather than 22.

---

## Data model

Follow the split the codebase already uses — **JSON files are documents, SQLite
is the registry.**

**Chat files** get one new optional field. No migration; existing chats read as
unfiled.

```json
{ "timestamp": "...", "agent": "author", "project": "moonlight-novel", ... }
```

**SQLite** gets a `projects` table, alongside `agents` and `tools`:

| column | purpose |
|---|---|
| `id` | slug, e.g. `moonlight-novel` |
| `name` | display name |
| `instructions` | prepended to the system message for every chat in the project |
| `default_agent` | selected when the project is opened |
| `default_provider`, `default_model` | ditto |
| `budget_eur` | optional per-project daily cap (nullable = no cap) |
| `archived` | hide from the picker without deleting |
| `created_at` | ordering |

Seeded through `_migrate_registry` like the others, so a fresh install and an
existing one converge.

---

## Tasks

### 2.1 — Storage and registry  *(no UI)*
- [ ] `projects` table in `services/database.py` + migration
- [ ] `Registry.list_projects()` / `get_project()` / `upsert_project()` /
      `archive_project()`
- [ ] `HistoryStore.save_chat(..., project=None)` writes the field
- [ ] Tests: round-trip a project, and confirm a chat with no `project` still
      loads (the backward-compatibility guarantee)

### 2.2 — Project selector in the sidebar
- [ ] Combo above the agent filter: *All projects · <projects> · Unfiled*
- [ ] Filter the list by project, combining with the existing agent filter and
      search (all three must intersect, not override each other)
- [ ] "Assign to project…" on the right-click menu of a saved chat
- [ ] New chats inherit the currently selected project

### 2.3 — Instructions injection  *(the core of Stage 2)*
- [ ] Prepend `project.instructions` to the system message in
      `build_tool_messages()` and in the agent `build_messages()` path
- [ ] Show the active project in the agent header bar so it is never a surprise
      what context is being sent
- [ ] Count the instructions in the cost estimate — they are billed tokens, and
      `estimate_chat_cost()` currently sees only the prompt
- [ ] Tests: a project's instructions appear exactly once, in the system message,
      and never leak into a chat from another project

### 2.4 — Defaults on open
- [ ] Selecting a project applies its `default_agent` / provider / model
- [ ] Never override a choice the user just made by hand — apply on project
      switch only
- [ ] "Save current setup as project defaults" action

### 2.5 — Per-project budget
- [ ] `budget_eur` enforced in `authorize_request()` via a new `Validator` rule,
      mirroring rule 7's shape and message
- [ ] Project spend readout in the BUDGET card when a project is active
- [ ] Tests alongside the existing budget tests in `tests/test_cost_and_limits.py`

### 2.6 — Management UI
- [ ] Projects tab in the Settings dialog (`ui/dialogs.py`) — create, rename,
      edit instructions, set defaults and budget, archive
- [ ] Delete leaves chats intact and marks them unfiled — never cascade-delete
      conversations

---

## Sequencing

2.1 → 2.2 gives working grouping with no behaviour change and is safe to ship
alone. 2.3 is where the feature becomes worth having. 2.4–2.6 are refinements
and can land in any order.

Stop after 2.2 if it turns out grouping was the whole itch — that is a real
possibility worth testing before building the rest.

---

## Risks and decisions

**Sidebar space.** The saved-chats list is capped at `setMaximumHeight(200)` in
an already dense sidebar, and Stage 1 has added a filter combo. A project combo
makes three controls above a 200px list. Either raise the cap, or replace the
flat list with a `QTreeWidget` grouping by project — the tree is nicer but takes
vertical space from the agent menu.

**Instructions are billed tokens.** Long project instructions silently raise the
cost of every request in that project. The estimate must include them (task 2.3)
or the BUDGET card will understate spend — the same class of bug as TODO #1,
where the numbers looked fine because the code path was never counted.

**Do not let projects become a second agent registry.** A project selects and
augments agents; it must not define its own tools or permissions. If a project
needs its own allowed-provider list, that belongs in the registry.

**Migration is a non-event by design** — the new field is optional and unfiled
chats stay valid. Keep it that way; do not add a required `project` field later.

---

## Not in scope

Project knowledge files (attach a PDF/EPUB whose content is retrieved into
context) — that is Stage 3. The extraction already exists in the narrator and
manuscript agents, but retrieval, chunking, and their token cost are a separate
piece of work and should not be smuggled into Stage 2.
