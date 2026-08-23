# BUG SPRAY — Bug bounty triage & reporting

`key: bug_bounty` · class: `agents/bug_bounty_agent.py → BugBountyAgent` · panel: `ui/panels/bug_bounty.py → BugBountyPanel`

> ⚠️ Only analyse assets explicitly in-scope for an authorised program.

## What it does
Turns raw findings into a professional vulnerability report and a paste-ready HackerOne/Bugcrowd submission. Has a **built-in nmap runner** (real subprocess) so recon and reporting live in one place. Output is CWE-classified with a CVSS v3.1 score.

## Inputs (panel controls)
| Control | Purpose |
|---|---|
| Target | In-scope asset (endpoint/host/component). |
| Program | Bug bounty program name. |
| Scope type | Web / Mobile / API / Network, etc. |
| Findings box | Paste HTTP responses, Burp output, source snippets, recon notes. |
| Optional reconnaissance | Collapsed Nmap controls; local scan output feeds the analysis. |
| Model override | Optional provider/model change; a strong security-reasoning model is selected by default. |
| Analyse / Stop | Run, or cancel while a request is active. Save and Clear appear with results. |

## Outputs
Tabs: **Full Report** (Vulnerability Title, Severity+CVSS, Target, Description, PoC, Impact, Remediation, References), **Vulnerability**, **PoC Draft**, **Remediation**, **Submission Draft** (platform-ready). Sidebar indicators (severity/lean) parsed from the report.

## How it works
`BugBountyAgent.build_messages(target, program, scope_type, findings, nmap_output)` composes only the evidence present (no fabrication) and requests the fixed report + submission format. Nmap runs via a dedicated `QProcess` (`bb_run_nmap` → `_bb_nmap_read` → `_bb_nmap_finished`), separate from the LLM `ChatWorker`.

## Under the hood — files & functions
| Location | Role |
|---|---|
| `agents/bug_bounty_agent.py` | `BugBountyAgent` — report + submission spec. |
| `ui/panels/bug_bounty.py` | Panel, optional Nmap lifecycle, three consolidated result tabs, analysis, and indicators. |
| `main.py: bb_save()/bb_clear()` | Export / reset. |

## Extend it
- **More recon tools**: mirror the nmap subprocess pattern for `nuclei`, `ffuf`, `subfinder` (add a box + `QProcess` runner, feed output into `bb_analyse()`).
- **Auto-severity**: post-process the report to set the sidebar from the parsed CVSS.
- **Program templates**: branch the submission format on the Program field.

## Requirements
`nmap` installed locally for the scanner. Provider key for analysis. Report is only as good as the evidence pasted.
