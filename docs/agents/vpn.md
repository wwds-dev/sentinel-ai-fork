# TUNNEL — self-hosted VPN design & config builder

`key: vpn` · class: `agents/vpn_agent.py → VpnAgent` · panel: `build_vpn_panel()` · handlers: `vpn_run()` (advisor) · `vpn_build_config()` (builder)

> Defensive, self-hosted infrastructure only — a VPN you own end to end, on hosts you are authorised to run.

## What it does
Brings the domain knowledge of the standalone **VPN Agent** app into Sentinel as one agent in the list. Two halves:
1. **Advisor** — an LLM that reasons from a structured system prompt about remote vs native topology, WireGuard vs the OpenVPN 443 fallback, the fail-closed kill switch, and DNS/IPv6/WebRTC leaks. Answers as SUMMARY · TOPOLOGY · SECURITY & LEAKS · COMMANDS/CONFIG · RECOMMENDATIONS.
2. **Config & Deploy Builder** — deterministic and offline: renders a WireGuard **server** + **client** config plus a numbered stand-up runbook, an optional OpenVPN TCP/443 fallback, and (remote mode) a macOS kill-switch pf snippet. No LLM, no network, no crypto dependency — keys are clearly-marked placeholders next to the exact `wg genkey` commands that fill them.

## Remote vs Native (the choice the agent keeps you honest about)
| | Remote (VPS) | Native (home LAN) |
|---|---|---|
| Runs on | a rented VPS, over SSH | hardware you own on your LAN |
| Traffic exits at | the server | your own home ISP |
| Hides your IP | yes | **no** |
| Changes apparent country | yes | **no** |
| Default routing | full tunnel (`0.0.0.0/0`) | split tunnel (LAN subnet) |

Native mode is an encrypted way **into** your network (NAS, printer, router), not a new way out.

## Inputs (panel controls)
| Control | Purpose |
|---|---|
| Mode | `Remote (VPS)` or `Native (home LAN)`. |
| Protocol | `WireGuard` · `OpenVPN 443 fallback` · `Both`. |
| Server host | VPS IP / DDNS hostname → the client config `Endpoint`. |
| SSH user | Used in the remote deploy runbook. |
| LAN subnet | Native mode split-tunnel `AllowedIPs`. |
| Egress iface | Server NIC for the NAT `MASQUERADE` rule (default `eth0`). |
| Question | Free-text for the Advisor. |
| Ask Advisor / Build Config / Stop / Help | LLM answer · offline render · cancel · docs. |

## Outputs
Tabs: **Advisor** (LLM answer) and **Config & Commands** (rendered configs + runbook). The deployment setup is passed to the advisor as context, so a question inherits the mode/protocol/host you picked.

## How it works
- `VpnAgent.build_messages(prompt)` → system prompt + the context-prefixed question; runs through `ChatWorker` like the other agents.
- `build_configs(mode, protocol, server_host, ssh_user, lan_subnet, egress_iface)` returns the whole config + runbook as text — pure string assembly, so it is instant and safe to run offline.

## Under the hood — files & functions
| Location | Role |
|---|---|
| `agents/vpn_agent.py` | `SYSTEM_PROMPT`, `build_configs()` + helpers, `VpnAgent`. |
| `main.py: build_vpn_panel()` | Panel, tabs, provider row. |
| `main.py: vpn_run()` | Advisor request (`ChatWorker`). |
| `main.py: vpn_build_config()` | Offline config/runbook render. |
| `services/database.py: _seed_default_agents()` | Registers the `vpn` agent row. |

## Extend it
- **Real keys**: swap the placeholder key material for locally-generated X25519 keys (the standalone VPN Agent does this via `cryptography`); keep them out of chat logs.
- **More topologies**: add site-to-site or multi-peer variants to `build_configs()`.
