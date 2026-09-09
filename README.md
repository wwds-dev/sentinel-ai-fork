# Sentinel Fork

Sentinel Fork is a local-first PySide6 desktop command centre for security, investigation, and controlled AI-assisted workflows. It supports local Ollama models and explicitly enabled cloud providers, records request usage and cost, and keeps each specialist workflow behind a clear panel and permission gate.

Sentinel's built-in roster is intentionally limited to seven agents:

| Display name | Key | Responsibility |
|---|---|---|
| Chat | `chat` | General conversation plus Writing, Coding, Summarize, and Rewrite tools |
| Trace | `osint` | Focused open-source research and source-led investigation planning |
| Bloodhound | `osint_heavy` | Deep OSINT dossiers plus read-only file discovery in user-selected folders |
| Beacon | `wifi` | Wi-Fi diagnostics and commands for networks the operator is authorised to test |
| Bug Spray | `bug_bounty` | In-scope vulnerability analysis and submission-ready bug bounty reports |
| Tunnel | `vpn` | Self-hosted WireGuard/OpenVPN design, configuration, and troubleshooting |
| Forge | `manager` | Creates and reviews specifications for new agents and tools |

Writing and Coding are Chat tools, not standalone agents. Creative publishing, audiobook, health, investing, and sports-betting workflows are not part of the current Sentinel product.

## Run locally

Requirements:

- Python 3.11 or newer
- the packages in `requirements.txt` (runtime) or `requirements-dev.txt` (development and builds)
- Ollama for local inference, or an API key for any cloud provider you choose to enable

From the project directory:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python main.py
```

API keys are read from the process environment or the project `.env` file in development. Supported provider variables include:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
DEEPSEEK_API_KEY
GOOGLE_API_KEY
KIMI_API_KEY
DASHSCOPE_API_KEY
DASHSCOPE_BASE_URL
```

Only enable a paid provider when you intend to use it. Sentinel checks provider permissions and configured budgets before a request, then records the resulting run and usage. Kimi's cached-input rate is priced separately from its base input rate (roughly 80% cheaper), so a request that reuses recent context costs less than the headline per-token estimate would suggest.

## Using the app

Choose an agent from the left sidebar. Chat uses the shared centre workspace; each specialist has its own panel with the inputs and actions relevant to that workflow. Provider and model controls remain explicit, and the recommended selection is highlighted where available.

Chat's Tool selector changes its system guidance:

- **General Chat** for open-ended assistance
- **Writing** for editing, tone, clarity, and structure
- **Coding** for code generation, explanation, debugging, and refactoring
- **Summarize** for condensation and key points
- **Rewrite** for rephrasing while preserving meaning

Type a message and press **Enter** to send; **Shift+Enter** inserts a newline
instead of sending. The transcript — labelled **Conversation** — shows every
message with a role and a timestamp (`YOU · 31 Aug 2026 · 10:15`).

Every agent, Chat included, has an **Auto-route** button next to its run
controls: it asks the router for a recommended provider and model for the
current input and applies the choice directly. Any provider or model other
than Ollama is marked as a paid selection (an amber marker on the dropdown),
so a cloud route is visible before you run it, not only after the cost is
logged.

Saved chats can be searched and filtered by agent. The two side rails split by what they carry rather than by left/right habit: the right rail is the live request inspector — Current Route, Cost, Budget, System, in that order, so the cards read top-to-bottom in the order a request actually happens — while API Keys and Actions (Cost history, Run log, Settings) sit in the left rail with the agent list, since those are global setup rather than per-request state. Settings controls registered agents, tools, pricing, and provider permissions.

The in-app **Learning Centre** is available from **More (•••)**. It contains a
guided Quick Start, full workspace and Settings reference, courses for all
seven agents, privacy/cost guidance, troubleshooting, multi-agent workflows,
practice exercises, current-interface screenshots, and the v3 advanced-tools
roadmap. Training source files live in `docs/training/`; they are separate from
the developer reference in `docs/agents/`.

For a removable, self-contained macOS copy, see
[`docs/portable_mode.md`](docs/portable_mode.md). Portable mode keeps settings,
history, logs and API-key storage on the removable volume and never silently
mixes them with the Lab checkout or Application Support. Its portable-only
**Settings → General → Emergency Reset** can erase Sentinel-owned data and API
keys after two confirmations. It is a privacy reset, not a Tails-style amnesic
session or forensic wipe: macOS, network equipment and providers may retain
separate records, and files deliberately exported elsewhere are not removed.

Bloodhound's **File Discovery** searches only locations you deliberately enter.
It supports folders on this Mac and owned macOS/Linux machines reachable by
SSH. Remote searches use SFTP with the SSH agent, `~/.ssh/config`, and strict
`known_hosts` verification; Sentinel stores no password or private key. Search
filters include full or partial name, extensions, size, and modified date.
Results show name, path, type, size, and modified time. Searches read metadata
only, never send file information to an AI provider, do not follow directory
links, and stop at safety limits. They cannot change files. **Open SSH Terminal**
hands an explicitly entered host to the operating system's normal SSH client
for interactive administration outside Sentinel.

### Safety boundaries

Beacon, Bug Spray, and Tunnel are intended for systems, networks, and programs the operator owns or is explicitly authorised to assess. Trace and Bloodhound should be used lawfully and with respect for privacy. Bloodhound never scans a local or remote machine automatically: the operator must enter each host and folder and already possess valid SSH access. Generated commands and findings require human review before execution or submission.

Forge writes an agent scaffold and inactive registry entries after review. Sentinel does not dynamically load it or add it to the sidebar; inspect, test, and deliberately integrate generated code before enabling it, especially when it adds tools or external access.

## Architecture

The main runtime is organised around:

- `main.py` — application window, Chat workflow, navigation, shared request controls
- `agents/` — built-in agent prompts and message builders
- `ui/panels/` — specialist panels for Trace, Bloodhound, Beacon, Bug Spray, Tunnel, and Forge
- `services/agent_catalog.py` — canonical built-in roster and metadata
- `services/registry.py` and `services/validator.py` — permissions and tool/provider checks; `registry.py` also has a `projects` table with full CRUD (`docs/projects_roadmap.md`, Stage 2) that nothing in the UI reads or writes yet
- `services/database.py` — SQLite schema and built-in registration
- `services/*_client.py` — local and cloud model clients
- `services/usage_tracker.py` and `services/run_logger.py` — cost and request lifecycle records
- `config/tool_prompts.json` — Chat tool instructions
- `data/sentinel.db` — local application data
- `assets/` — `icon.icns` and its source PNG for the macOS app bundle; used by
  `scripts/install_app.sh`, `scripts/build_app.sh`, and `SentinelAI.spec`
- `output/` — gitignored, generated-only. Currently holds leftover files from
  before this fork was narrowed to the security roster (`launch_assets/` has a
  KDP listing, an ARC outreach email and a BookTok pitch — publishing-agent
  output, not something this Sentinel builds). Safe to clear; nothing in this
  repo reads from it.

Built-in agents come from the canonical catalog. Forge-generated agents use the dynamic registry and remain separate from the built-in roster.

## Data and configuration

Development runs and the everyday thin launcher use the Lab project directory for writable data. Self-contained release builds use Sentinel's application-support directory. Runtime-path handling and initial seed copying live in `services/runtime_paths.py`.

### macOS launch modes

`./scripts/install_app.sh` installs the everyday thin launcher. It runs directly from this Lab checkout and uses this folder's `data/`, `config/`, and `.env`, exactly like `python main.py`.

`./scripts/build_app.sh` creates a self-contained release in `dist.noindex/` but does not install it. A self-contained build uses `~/Library/Application Support/Sentinel Fork/` when launched. Installing it with `./scripts/build_app.sh --install` explicitly replaces the thin launcher, so use that option only when you intend to switch modes. The two modes do not automatically merge their data.

Important data includes saved chats, settings, usage, run history, and registry records. Do not replace or delete `data/sentinel.db` during an upgrade. Schema and roster changes should be applied through migrations that preserve user history.

Do not commit `.env`, credentials, generated reports containing sensitive information, or private investigation data.

## Testing

Run the automated suite from the activated environment:

```bash
pytest
```

The current manual acceptance checklist is in `tests/manual_test_cases.md`. It covers all seven built-in agents and verifies that Writing and Coding remain Chat tools rather than sidebar agents.

## Further documentation

Agent-specific reference guides live in `docs/agents/`: `chat.md`, `osint.md`, `osint_heavy.md`, `wifi.md`, `bug_bounty.md`, `vpn.md`, and `manager.md`.
User training and the course roadmap live in [`docs/training/`](docs/training/).

Documents describing the workspace split or earlier architecture are historical records. They explain how features moved between projects; they do not define current Sentinel behaviour.
