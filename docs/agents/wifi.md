# BEACON — Wi-Fi reconnaissance & Kali command builder

`key: wifi` · class: `agents/wifi_agent.py → WiFiAgent` · panel: `ui/panels/wifi.py → WifiPanel`

> ⚠️ Only test networks you own or have written authorisation to assess.

## What it does
Two capabilities in one panel:
1. **Live macOS diagnostics** — runs real subprocesses (the `airport` utility, `ping`, interface queries) and shows raw output.
2. **Offensive tooling** — detects known USB Wi-Fi adapters and generates ready-to-run **Kali Linux** command sequences (aircrack-ng / hashcat) for authorised testing. An optional **AI Analysis** step feeds the raw scan output to an LLM for interpretation.

## Inputs (panel controls)
| Control | Purpose |
|---|---|
| Mode | `Interface Info` · `Scan Networks` · `Signal Monitor` · `Ping Test` · `Kali Command Builder`. |
| Interface | Network interface (e.g. `en0`). |
| Target Host | Used by Ping Test. |
| Kali sub-form (hidden unless Kali mode) | Operation (`Handshake Capture` / `Deauth Attack` / `WPS Audit` / `PMKID Attack`), Adapter, BSSID, Channel, ESSID. |
| AI interpretation | Optional collapsed section, off by default. Enable it to send subprocess output to the selected LLM. |
| Detect Adapters | Scan USB for known adapters. |
| Run / Stop | Execute, or cancel while work is active. Results reveal Save and Clear controls. Use the shared Help button for docs. |

## Outputs
Tabs: **Raw Output** (subprocess text), **AI Analysis** (LLM interpretation), **Kali Commands** (generated sequence). Sidebar: detected adapter, chipset, capabilities (monitor/injection), signal bar, security.

## How it works
- `detect_usb_adapters()` parses `system_profiler SPUSBDataType -json` against `KNOWN_ADAPTERS` (VID/PID → chipset, monitor/inject support, Kali iface, driver notes).
- `build_kali_commands(operation, adapter, bssid, channel, essid)` returns a numbered, commented command block; refuses injection ops on adapters that can't inject.
- Live modes run via `SubprocessWorker` (QThread). AI Analysis routes raw output through `ChatWorker` + `WiFiAgent.build_messages()`.

## Under the hood — files & functions
| Location | Role |
|---|---|
| `agents/wifi_agent.py` | `KNOWN_ADAPTERS`, `AIRPORT` path, `detect_usb_adapters()`, `build_kali_commands()`, `WiFiAgent`. |
| `ui/panels/wifi.py` | Panel and dispatch by Mode (subprocess vs Kali build vs optional AI). |
| `main.py: SubprocessWorker` | Runs shell commands off the UI thread. |

## Extend it
- **Add an adapter**: add a `(vid, pid): {...}` entry to `KNOWN_ADAPTERS`.
- **Add a Kali operation**: add a branch in `build_kali_commands()` (respect the `inject` capability check).
- **Add a live mode**: add a Mode option and a subprocess command in `wifi_run()`.

## Requirements
macOS `airport` binary (built-in path in `AIRPORT`). Kali commands assume a Kali box + compatible adapter (user's: TL-WN722N, AWUS036ACH, TL-WN725N V3). AI Analysis needs a provider key.
