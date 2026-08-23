"""Canonical built-in agent roster for the Sentinel security hub.

Dynamic agents created by Forge live in SQLite and are deliberately not part of
this catalog. Retired names are kept only so existing installations can stop
showing agents that moved to another application; historical runs and chats are
never deleted.
"""

BUILTIN_AGENTS = {
    "chat": {
        "label": "Chat",
        "icon": "▸",
        "subtitle": "General reasoning, any provider",
        "tooltip": "General-purpose conversation. Pick a tool, pick a model, talk.",
        "description": "General-purpose chat agent.",
        "allowed_tools": ["General Chat", "Writing", "Coding", "Summarize", "Rewrite"],
        "budget_limit_eur": None,
    },
    "manager": {
        "label": "Forge",
        "icon": "✦",
        "subtitle": "Create reviewable agent scaffolds",
        "tooltip": "Describe a new agent in plain language and create a reviewable scaffold.",
        "description": "Builds and reviews new agents and tools.",
        "allowed_tools": None,
        "budget_limit_eur": None,
    },
    "osint": {
        "label": "Trace",
        "icon": "◈",
        "subtitle": "Open-source identity research",
        "tooltip": "Light OSINT — structured research queries.",
        "description": "Open-source intelligence research and investigation agent.",
        "allowed_tools": ["General Chat", "Summarize"],
        "budget_limit_eur": 2.0,
    },
    "osint_heavy": {
        "label": "Bloodhound",
        "icon": "◉",
        "subtitle": "Deep investigation and dossier",
        "tooltip": "Deep OSINT investigation with a structured dossier.",
        "description": "Deep structured investigation dossiers and live OSINT synthesis.",
        "allowed_tools": None,
        "budget_limit_eur": None,
    },
    "wifi": {
        "label": "Beacon",
        "icon": "≋",
        "subtitle": "Wireless reconnaissance",
        "tooltip": "Wireless reconnaissance, signal analysis, and authorised diagnostics.",
        "description": "Wi-Fi diagnostics and authorised wireless-security workflows.",
        "allowed_tools": None,
        "budget_limit_eur": None,
    },
    "bug_bounty": {
        "label": "Bug Spray",
        "icon": "⌁",
        "subtitle": "Vulnerability triage",
        "tooltip": "Vulnerability triage and bug-bounty submission drafts.",
        "description": "Authorised vulnerability analysis and bug-bounty report generation.",
        "allowed_tools": None,
        "budget_limit_eur": None,
    },
    "vpn": {
        "label": "Tunnel",
        "icon": "⇄",
        "subtitle": "Self-hosted VPN design & kill switch",
        "tooltip": "Self-hosted VPN design, deployment, and troubleshooting.",
        "description": "Self-hosted VPN design, configuration, and troubleshooting.",
        "allowed_tools": None,
        "budget_limit_eur": None,
    },
}

BUILTIN_AGENT_ORDER = (
    "chat", "osint", "osint_heavy", "wifi", "bug_bounty", "vpn", "manager",
)

# These were once Sentinel built-ins. Their application data is preserved in
# sibling projects; this list only retires their registry rows in Sentinel.
RETIRED_BUILTIN_AGENTS = frozenset({
    "audiobook", "author", "coding", "fiverr", "health", "investment",
    "manuscript", "music", "nfl_bet", "ops_identity", "roi", "webdesign",
    "writing",
})
