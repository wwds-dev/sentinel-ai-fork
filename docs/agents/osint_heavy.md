# BLOODHOUND — Deep OSINT investigation

`key: osint_heavy` · class: `agents/osint_heavy_agent.py → OsintHeavyAgent` · panel: `ui/panels/osint_heavy.py → OsintHeavyPanel`

## What it does
Produces a research-grade, five-section intelligence dossier on a target, with an embedded threat score, confidence score, and a curated tradecraft tool library (~60 tools grouped by target type: people, username, email, domain/IP, breach, phone, image, archive, geolocation). Accepts an optional **image** and folds its EXIF metadata into the analysis. It also provides **Local File Discovery**, a separate read-only search for files in folders the user deliberately selects. File-search metadata never enters an AI prompt or leaves the device.

## Inputs (panel controls)
| Control | Purpose |
|---|---|
| Target identifier | Person / username / email / domain / IP / organisation. |
| Target type | Guides which tool families and pivots are emphasised. |
| Scope | `Quick Scan` (3–5 pts/section), `Standard`, or `Deep Dive` (exhaustive). |
| Objective / context | Free-text investigation goal. |
| Add target image | Optional collapsed section; EXIF is parsed and injected into the prompt. |
| Model override | Optional provider/model change; a long-context reasoning model is selected by default. |
| Investigate / Stop | Run, or cancel while a request is active. Save and Clear appear with results. |

## File Discovery

Expand **File Discovery — selected locations only**. Choose **This Mac** and add
folders, or choose **Remote SSH machine** and enter an owned machine's hostname,
IP address, or `~/.ssh/config` alias, SSH user, port, and absolute remote paths.
Remote discovery uses SFTP, your existing SSH agent/keys, and strict
`known_hosts` verification. Sentinel does not store passwords or private keys.

Searches can match a full or partial file name, a comma-separated list
of extensions, minimum/maximum size in MB, and an optional modified-date range.
The result table shows name, full path, type, size, and modified time.
Double-clicking a result reveals its containing folder.

The search is deliberately separate from dossier generation. Local and remote
searches read file
metadata only, never reads file contents, never uploads paths or results, never
follows directory symbolic links, and cannot change files. Cancellation keeps
matches already found. Searches stop after 5,000 matches or 250,000 inspected
entries; select a smaller folder or narrower filters to continue. **Open SSH
Terminal** opens the operating system's SSH handler for an interactive session;
arbitrary remote commands are not executed inside Sentinel or by its AI worker.

## Outputs — the dossier (exact section headers the parser keys off)
`## 1. OVERVIEW` (with `THREAT LEVEL: X/10`, `CONFIDENCE: X%`, `SOURCES REFERENCED: X`) · `## 2. DIGITAL FOOTPRINT` · `## 3. INFRASTRUCTURE / SOCIAL PROFILE` · `## 4. RISK & RED FLAGS` · `## 5. METHODOLOGY & TOOLS`. Sidebar indicators (threat bar, confidence, sources) are regex-parsed from those exact lines.

## How it works
`OsintHeavyAgent.build_messages(target, target_type, scope, objective, image_metadata)` assembles the target + scope hint + optional EXIF block. The system prompt carries the full tool library and the strict section format the UI depends on.

## Under the hood — files & functions
| Location | Role |
|---|---|
| `agents/osint_heavy_agent.py` | `OsintHeavyAgent` + the tool library + section spec. |
| `ui/panels/osint_heavy.py` | Panel, optional image workflow, consolidated result tabs, and indicators. |
| `services/local_file_search.py` | Bounded, read-only metadata search and filters. |
| `services/remote_file_search.py` | Strict-host-key SFTP traversal for authenticated machines. |
| `ui/workers.py: LocalFileSearchWorker` | Runs file discovery without freezing the interface. |
| `main.py: osint_heavy_investigate()` | Reads form + EXIF, fires `ChatWorker`. |
| `main.py: osint_heavy_save()` | Saves dossier to `.txt`. |

## Extend it
- **New tool family**: add a block to the tool library in the system prompt (keep the `Name: URL — description` format).
- **New indicator**: emit a new `KEY: value` line in section 1 and parse it in the panel's indicator update.
- **Live pivots**: enrich `osint_heavy_investigate()` with `providers/*_lookup.py` before sending.
- Keep section headers verbatim — the parser matches them exactly.

## Requirements
A large-context reasoning model is recommended automatically. Optional OSINT API keys in `.env`. Pillow (bundled) handles EXIF. Local search uses the Python standard library. Remote search requires Paramiko and an existing SSH identity; neither mode requires an AI model or API key.
