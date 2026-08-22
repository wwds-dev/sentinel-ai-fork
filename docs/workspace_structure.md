# Workspace structure — the target shape

Supersedes `docs/app_split.md`, which proposed three home apps. This is the
agreed structure: **four app hubs plus Lab Hub as the front desk.**

## The four hubs

### Sentinel — security and intelligence
Renamed from "Sentinel" to **Sentinel** everywhere: window title, bundle
name, `runtime_paths.APP_NAME`, the single-instance key, the installed
`/Applications` bundle, the Lab Hub tile, and the repo's own docs.

| agent | current name | source |
|---|---|---|
| VPN Agent | — | **integrated** from the standalone `vpn_agent` project |
| Trace | `osint` | stays |
| Bloodhound | `osint_heavy` | stays |
| Beacon | `wifi` | stays |
| Bug Spray | `bug_bounty` | stays |

VPN Agent stops being a separate launchable app and becomes a Sentinel agent.

### SONAR — markets and wagering
Already exists. Gains its own tabs for:

- **Oracle** — long-term investment monitoring
- **Playmaker** — the betting tool, never a standalone project. NFL shipped
  (`sonar/sports.py`, odds arithmetic + 33 tests); the sport registry is the
  extension point for the rest

### Create & Publish — creative and publishing
This is the `atelier` fork, renamed. Contents:

| agent | current name | source |
|---|---|---|
| Website creator | `webdesign` | Sentinel |
| vidforge | — | **integrated** from the standalone `vidforge` project |
| Fiverr | `fiverr` | Sentinel |
| Maestro | `music` | Sentinel |
| Manuscript | `author` | Sentinel |
| Publisher | `manuscript` | Sentinel |

Note the naming collision to be careful with: Sentinel's `author` agent is
displayed as "Manuscript", and its `manuscript` agent is displayed as
"Publisher". Both move; the internal keys should be renamed to match their
display names during the move, or this stays confusing forever.

### Backup & Sync — the maintenance hub
A standalone app in the same shape as Sentinel, holding two apps that are
currently separate:

- Backup Control Center (`backup_manager`)
- git_autosync

Both remain runnable from within it.

## Lab Hub — the front desk

Everything opens from Lab Hub's tiles. A hub tile shows its own name with the
apps and agents it contains listed beneath in a smaller font:

    ┌─────────────────────────┐  ┌─────────────────────────┐
    │ Sentinel                │  │ SONAR                   │
    │ VPN · Trace · Bloodhound│  │ Terminal · Assets ·      │
    │ Beacon · Bug Spray      │  │ Oracle · Sports          │
    └─────────────────────────┘  └─────────────────────────┘
    ┌─────────────────────────┐  ┌─────────────────────────┐
    │ Create & Publish        │  │ Backup & Sync           │
    │ Website · vidforge ·     │  │ Backup Control Center · │
    │ Fiverr · Maestro ·       │  │ git_autosync            │
    │ Manuscript · Publisher   │  │                         │
    └─────────────────────────┘  └─────────────────────────┘

### Tools tab
A new Lab Hub tab presenting small utilities as tiles, replacing the current
Convert Files / Prepare Images tabs:

- **Narrator** — the ebook→audiobook converter, moved out of Sentinel
- **Unblock Tracker** — moved off the Apps tile grid
- **Convert** — `convert_epub`
- **Image tools** — `image_tools`

## Decided (2026-08-12)

- **`chat` stays in Sentinel** — one general assistant, in the security hub.
  The `normal_panel` machinery stays with it.
- **`manager` stays in Sentinel** — it is where new agents get made, and the
  registry it edits already lives here.
- **`audiobook` leaves Sentinel.** The agent and its panel come out; the
  Narrator service backs the Lab Hub tool tile.

So Sentinel's final roster is seven: chat · manager · VPN Agent · Trace ·
Bloodhound · Beacon · Bug Spray.

## What has to happen

Ordered so nothing is untangled twice. The refactor still gates the moves — see
`docs/refactor_plan.md`.

### Sentinel
1. Rename "Sentinel" → "Sentinel" everywhere (see the trap list below).
2. Finish refactor phases 3–5 so each agent is a self-contained module.
3. Extract the shared platform package — provider clients, request guard,
   budget/usage/registry, `ui/{style,widgets,workers,dialogs}`. Every hub
   consumes it. Without this, four apps grow four diverging copies of the money
   logic, which is TODO #1 repeated four times.
4. Integrate VPN Agent as an agent.
5. ~~Remove the agents that leave.~~ **DONE (2026-08-12).** `audiobook`,
   `webdesign`, `fiverr`, `music`, `author` and `manuscript` are out, along with
   their eight services (`narrator/`, `course/`, `book_exporter`,
   `kdp_csv_parser`, `publishdrive_client`, `quote_graphics`,
   `shorts_generator`, `content_calendar`), `ui/book_widgets.py`, their agent
   modules, docs, test classes, seed entries and DB rows. `main.py` 9,034 →
   **5,225 lines**; sidebar down to the six that stay. All of it is preserved in
   the `atelier` fork, which is why this was safe to do before the refactor.

   One trap worth recording: the deletion matched method names by substring, and
   **`authorize_request` contains "author"** — so the request guard was silently
   removed. The test suite caught it (24 failures), and it was restored from the
   pre-deletion copy. Same family as "i*nfl*uences" matching an `nfl` search:
   never match agent names as bare substrings.

### Create & Publish
6. Rename the `atelier` repo and app to Create & Publish.
7. Take the platform package; delete the security verticals and `providers/`.
8. Integrate vidforge.
9. Re-shape as tabs; rename `author`→Manuscript and `manuscript`→Publisher
   internally.

### SONAR
10. Oracle tab (long-term investment monitoring).
11. More sports as the registry allows.

### Backup & Sync
12. New app shell in the same shape as Sentinel; embed Backup Control Center
    and git_autosync so both run from inside it.

### Lab Hub
13. Hub tiles that list their contents in a smaller font.
14. Tools tab with Narrator, Unblock Tracker, Convert and Image tools as tiles.

## Rename traps

Every one of these has already bitten once in this workspace:

- `runtime_paths.APP_NAME` decides `~/Library/Application Support/<name>/`.
  Changing it moves where a packaged app keeps its database, chats and `.env`.
  Migrate the directory or the app looks freshly installed.
- `SINGLE_INSTANCE_KEY` — two apps sharing it means launching one focuses the
  other instead of opening.
- The `.app` launcher runs a specific project path; each hub needs its own.
- `Registry` reads the **SQLite database**, not `config/registry.json`. Moving
  an agent means moving its row, not just the seed entry.
- Lab Hub's `launcher.py` matches installed bundles by display name, so a
  renamed bundle needs its `ExternalApp.name` updated in the same commit.
