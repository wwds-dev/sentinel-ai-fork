"""
Sentinel — Agent Scenario Tests
===================================
Type: Functional / Scenario-based Tests  (also called "Use Case Tests")

These tests verify that every agent:
  1. Produces a correctly structured message list for the LLM.
  2. Injects the right system prompt for its domain.
  3. Embeds every piece of user-supplied input into the user message.
  4. Executes its own logic correctly (routing, parsing, config).

They are NOT unit tests of individual helper lines, and they are NOT
end-to-end tests that call a live LLM.  The sweet spot is: "given this
realistic scenario, does the agent behave exactly as designed?"

Run with:  pytest tests/test_agents_scenarios.py -v
"""

import json
import sys
import os
import pytest

# Make sure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.router_agent       import RouterAgent
from agents.manager_agent      import ManagerAgent
from agents.chat_agent         import ChatAgent
from agents.coding_agent       import CodingAgent
from agents.writing_agent      import WritingAgent
from agents.osint_agent        import OSINTAgent
from agents.osint_heavy_agent  import OsintHeavyAgent
from agents.bug_bounty_agent   import BugBountyAgent
from agents.wifi_agent         import WiFiAgent
from agents.vpn_agent          import VpnAgent, build_configs as build_vpn_configs


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _roles(msgs):
    """Return just the list of roles from a message list."""
    return [m["role"] for m in msgs]

def _system(msgs):
    """Return the content of the first system message, or None."""
    for m in msgs:
        if m["role"] == "system":
            return m["content"]
    return None

def _user(msgs):
    """Return the content of the last user message."""
    for m in reversed(msgs):
        if m["role"] == "user":
            return m["content"]
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. RouterAgent
# Scenario: classify six different inputs — all four routes, plus edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestRouterAgent:
    agent = RouterAgent()

    def test_routes_osint_on_email(self):
        assert self.agent.classify("Look up the email john.doe@example.com") == "osint"

    def test_routes_osint_on_domain_keyword(self):
        assert self.agent.classify("Run a whois lookup on target domain") == "osint"

    def test_routes_coding_on_python_keyword(self):
        assert self.agent.classify("I have a bug in my python script") == "coding"

    def test_routes_coding_on_debug_keyword(self):
        assert self.agent.classify("Help me debug this function") == "coding"

    def test_routes_writing_on_write_keyword(self):
        assert self.agent.classify("Write a cover letter for a data science role") == "writing"

    def test_routes_writing_on_blog_keyword(self):
        assert self.agent.classify("Draft a blog post about AI trends") == "writing"

    def test_defaults_to_chat(self):
        assert self.agent.classify("What is the capital of France?") == "chat"

    def test_case_insensitive_routing(self):
        # RouterAgent lowercases internally — verify uppercase inputs still route
        assert self.agent.classify("DEBUG this CODE please") == "coding"
        assert self.agent.classify("OSINT on this target") == "osint"


# ─────────────────────────────────────────────────────────────────────────────
# 2. ManagerAgent
# Scenario: build a spec request and parse both clean and fenced JSON responses
# ─────────────────────────────────────────────────────────────────────────────

class TestManagerAgent:
    agent = ManagerAgent()

    VALID_SPEC = {
        "name": "news_agent",
        "label": "News Agent",
        "description": "Summarises daily news headlines.",
        "allowed_providers": ["openai"],
        "allowed_tools": ["General Chat"],
        "budget_limit_eur": 2.0,
        "requires_approval": False,
        "system_prompt": "You are a news summariser.",
        "reasoning": "Needs internet access via OpenAI.",
    }

    def test_build_messages_structure(self):
        msgs = self.agent.build_messages("An agent that summarises daily news")
        assert _roles(msgs) == ["system", "user"]

    def test_build_messages_injects_idea(self):
        idea = "An agent that summarises daily news"
        msgs = self.agent.build_messages(idea)
        assert idea in _user(msgs)

    def test_build_messages_system_prompt_contains_schema(self):
        msgs = self.agent.build_messages("anything")
        sys_content = _system(msgs)
        # The schema field names must all be present in the system prompt
        for field in ["name", "label", "description", "allowed_providers",
                      "system_prompt", "requires_approval", "budget_limit_eur"]:
            assert field in sys_content

    def test_parse_spec_clean_json(self):
        raw = json.dumps(self.VALID_SPEC)
        result = self.agent.parse_spec(raw)
        assert result is not None
        assert result["name"] == "news_agent"
        assert result["label"] == "News Agent"
        assert result["budget_limit_eur"] == 2.0

    def test_parse_spec_with_markdown_fences(self):
        raw = f"```json\n{json.dumps(self.VALID_SPEC)}\n```"
        result = self.agent.parse_spec(raw)
        assert result is not None
        assert result["name"] == "news_agent"

    def test_parse_spec_returns_none_on_garbage(self):
        assert self.agent.parse_spec("Sorry, I cannot do that.") is None

    def test_parse_spec_returns_none_on_empty_string(self):
        assert self.agent.parse_spec("") is None

    def test_parse_spec_handles_extra_text_around_json(self):
        raw = f"Here is your spec:\n{json.dumps(self.VALID_SPEC)}\nHope that helps!"
        result = self.agent.parse_spec(raw)
        assert result is not None
        assert result["name"] == "news_agent"


# ─────────────────────────────────────────────────────────────────────────────
# 3. ChatAgent
# Scenario: pass a multi-line, conversational prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestChatAgent:
    agent = ChatAgent()

    def test_message_structure(self):
        msgs = self.agent.build_messages("Hello, how are you?")
        assert _roles(msgs) == ["user"]

    def test_user_content_preserved(self):
        prompt = "Explain quantum entanglement in simple terms."
        msgs = self.agent.build_messages(prompt)
        assert _user(msgs) == prompt

    def test_multiline_prompt(self):
        prompt = "Line one.\nLine two.\nLine three."
        msgs = self.agent.build_messages(prompt)
        assert "Line one" in _user(msgs)
        assert "Line three" in _user(msgs)

    def test_no_system_injection(self):
        # ChatAgent is intentionally system-prompt-free
        msgs = self.agent.build_messages("hi")
        assert _system(msgs) is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. CodingAgent
# Scenario: request to debug a real-looking broken Python snippet
# ─────────────────────────────────────────────────────────────────────────────

class TestCodingAgent:
    agent = CodingAgent()

    PROMPT = (
        "This function throws a KeyError but I can't see why:\n\n"
        "def get_user(data, uid):\n"
        "    return data[uid]['name']\n\n"
        "get_user({'42': {'name': 'Alice'}}, 99)"
    )

    def test_message_structure(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_user_content_preserved(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "KeyError" in _user(msgs)
        assert "get_user" in _user(msgs)

    def test_system_prompt_mentions_coding(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "coding" in _system(msgs).lower() or "code" in _system(msgs).lower()

    def test_system_prompt_mentions_debug(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "debug" in _system(msgs).lower()


# ─────────────────────────────────────────────────────────────────────────────
# 5. WritingAgent
# Scenario: ask to rewrite a rough paragraph for a professional audience
# ─────────────────────────────────────────────────────────────────────────────

class TestWritingAgent:
    agent = WritingAgent()

    PROMPT = (
        "Rewrite this for a professional audience:\n"
        "'We kinda messed up the deadline cause nobody checked the calendar lol'"
    )

    def test_message_structure(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_user_content_preserved(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "Rewrite" in _user(msgs)

    def test_system_prompt_mentions_writing_goals(self):
        sys = _system(msgs := self.agent.build_messages(self.PROMPT))
        writing_keywords = ["clarity", "tone", "readability", "writing"]
        assert any(k in sys.lower() for k in writing_keywords)


# ─────────────────────────────────────────────────────────────────────────────
# 6. OSINTAgent  (light)
# Scenario A: email auto-detect  |  Scenario B: explicit username query type
# ─────────────────────────────────────────────────────────────────────────────

class TestOSINTAgent:
    agent = OSINTAgent()

    def test_email_auto_detect_structure(self):
        msgs = self.agent.build_messages("suspect@darkmail.io")
        assert _roles(msgs) == ["system", "user"]

    def test_email_target_appears_in_user_message(self):
        msgs = self.agent.build_messages("suspect@darkmail.io")
        assert "suspect@darkmail.io" in _user(msgs)

    def test_auto_detect_no_type_hint_in_user(self):
        msgs = self.agent.build_messages("suspect@darkmail.io", "Auto-detect")
        # "Auto-detect" itself should NOT appear verbatim in the user message
        assert "Auto-detect" not in _user(msgs)

    def test_explicit_query_type_appears_in_user_message(self):
        msgs = self.agent.build_messages("h4x0r_pete", "Username")
        assert "Username" in _user(msgs)

    def test_system_prompt_contains_four_sections(self):
        sys = _system(self.agent.build_messages("test"))
        for section in ["QUERY STRUCTURE", "GOOGLE DORKS", "PUBLIC SOURCES", "SUMMARY"]:
            assert section in sys

    def test_system_prompt_mentions_google_operators(self):
        sys = _system(self.agent.build_messages("test"))
        assert "site:" in sys or "inurl:" in sys


# ─────────────────────────────────────────────────────────────────────────────
# 7. OSINTHeavyAgent  (deep investigation)
# Scenario: deep-dive on a suspicious domain with a specific objective
# ─────────────────────────────────────────────────────────────────────────────

class TestOSINTHeavyAgent:
    agent = OsintHeavyAgent()

    TARGET       = "phishkit-delivery.net"
    TARGET_TYPE  = "Domain / IP"
    SCOPE        = "Deep Dive"
    OBJECTIVE    = "Determine if this domain is linked to phishing infrastructure"

    def test_message_structure(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE
        )
        assert _roles(msgs) == ["system", "user"]

    def test_target_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE
        )
        assert self.TARGET in _user(msgs)

    def test_objective_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE
        )
        assert self.OBJECTIVE in _user(msgs)

    def test_scope_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE
        )
        assert self.SCOPE in _user(msgs)

    def test_deep_dive_scope_hint_injected(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, "Deep Dive", self.OBJECTIVE
        )
        assert "Deep Dive" in _user(msgs)

    def test_image_metadata_injected_when_provided(self):
        meta = "GPS: 48.8566° N, 2.3522° E  |  Device: iPhone 14  |  Date: 2024-11-01"
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE,
            image_metadata=meta
        )
        assert "GPS" in _user(msgs)
        assert "IMAGE METADATA" in _user(msgs)

    def test_no_image_metadata_when_omitted(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE
        )
        assert "IMAGE METADATA" not in _user(msgs)

    def test_system_prompt_contains_required_sections(self):
        sys = _system(self.agent.build_messages(
            self.TARGET, self.TARGET_TYPE, self.SCOPE, self.OBJECTIVE
        ))
        for section in ["OVERVIEW", "DIGITAL FOOTPRINT", "THREAT LEVEL", "CONFIDENCE"]:
            assert section in sys


# ─────────────────────────────────────────────────────────────────────────────
# 9. BugBountyAgent
# Scenario A: Full data (target + program + nmap + Burp findings)
# Scenario B: Partial data (no nmap output — common in early recon)
# ─────────────────────────────────────────────────────────────────────────────

class TestBugBountyAgent:
    agent = BugBountyAgent()

    TARGET   = "api.targetcorp.com/v1/user?id=1"
    PROGRAM  = "TargetCorp HackerOne Program"
    SCOPE    = "Web Application"
    FINDINGS = (
        "GET /v1/user?id=1 returns full user object.\n"
        "Changing id=1 to id=2 returns another user's data without auth check.\n"
        "Tested: id=1 through id=5 — all return distinct users. IDOR confirmed."
    )
    NMAP = (
        "PORT   STATE SERVICE VERSION\n"
        "80/tcp open  http    nginx 1.18.0\n"
        "443/tcp open https   nginx 1.18.0\n"
        "8080/tcp open http-proxy\n"
    )

    def test_full_data_message_structure(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        )
        assert _roles(msgs) == ["system", "user"]

    def test_target_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        )
        assert self.TARGET in _user(msgs)

    def test_program_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        )
        assert self.PROGRAM in _user(msgs)

    def test_nmap_output_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        )
        assert "nginx" in _user(msgs)

    def test_findings_in_user_message(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        )
        assert "IDOR" in _user(msgs)

    def test_no_nmap_still_builds_messages(self):
        msgs = self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, nmap_output=""
        )
        assert len(msgs) == 2
        assert "IDOR" in _user(msgs)

    def test_system_prompt_contains_vulnerability_report_structure(self):
        sys = _system(self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        ))
        for keyword in ["Severity", "Proof of Concept", "Remediation", "CVSS"]:
            assert keyword in sys

    def test_system_prompt_mentions_submission_draft(self):
        sys = _system(self.agent.build_messages(
            self.TARGET, self.PROGRAM, self.SCOPE, self.FINDINGS, self.NMAP
        ))
        assert "SUBMISSION" in sys or "HackerOne" in sys or "Bugcrowd" in sys


# ─────────────────────────────────────────────────────────────────────────────
# 17. WiFiAgent
# Scenario: analyse a macOS Wi-Fi scan on a crowded coffee shop network
# ─────────────────────────────────────────────────────────────────────────────

class TestWiFiAgent:
    agent = WiFiAgent()

    PROMPT = (
        "macOS airport scan — coffee shop:\n"
        "SSID: CoffeeHouse_Guest  BSSID: AA:BB:CC:DD:EE:FF  RSSI: -62  Channel: 6  "
        "Security: WPA2 Personal\n"
        "SSID: CoffeeHouse_Staff  BSSID: AA:BB:CC:DD:EE:F1  RSSI: -70  Channel: 11  "
        "Security: WPA2 Enterprise\n"
        "SSID: Free_WiFi_No_Pass  BSSID: 11:22:33:44:55:66  RSSI: -55  Channel: 1  "
        "Security: NONE\n"
        "Interface: en0  Mode: Station  TX Rate: 300 Mbps\n"
        "Adapter USB ID: 0bda:8812"
    )

    def test_message_structure(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_prompt_preserved(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "CoffeeHouse_Guest" in _user(msgs)
        assert "0bda:8812" in _user(msgs)

    def test_system_prompt_mentions_wireless_analysis(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "Wi-Fi" in sys or "wireless" in sys.lower() or "SSID" in sys

    def test_system_prompt_scoped_to_authorised_testing(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "authoris" in sys.lower() or "authorized" in sys.lower() or "pentest" in sys.lower()


# ─────────────────────────────────────────────────────────────────────────────
# VpnAgent — advisor messages + deterministic config builder
# ─────────────────────────────────────────────────────────────────────────────

class TestVpnAgent:
    agent = VpnAgent()
    PROMPT = "WireGuard won't connect on hotel wifi — what are my options?"

    def test_message_structure(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_prompt_preserved(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "hotel wifi" in _user(msgs)

    def test_system_prompt_covers_domain(self):
        sys = _system(self.agent.build_messages(self.PROMPT)).lower()
        assert "wireguard" in sys and "openvpn" in sys and "kill switch" in sys

    def test_system_prompt_scoped_to_self_hosted(self):
        sys = _system(self.agent.build_messages(self.PROMPT)).lower()
        assert "authoris" in sys or "defensive" in sys or "own" in sys


class TestVpnConfigBuilder:
    def test_remote_full_tunnel_and_killswitch(self):
        cfg = build_vpn_configs(
            "Remote (VPS)", "WireGuard",
            server_host="203.0.113.9", ssh_user="root", egress_iface="eth0",
        )
        assert "203.0.113.9:51820" in cfg     # endpoint wired from host
        assert "0.0.0.0/0" in cfg             # full tunnel
        assert "block drop all" in cfg        # kill switch present in remote

    def test_native_split_tunnel_no_killswitch(self):
        cfg = build_vpn_configs(
            "Native (home LAN)", "WireGuard", lan_subnet="192.168.1.0/24",
        )
        assert "192.168.1.0/24" in cfg        # split tunnel to LAN
        assert "0.0.0.0/0" not in cfg         # not a full tunnel
        assert "block drop all" not in cfg    # native mode: no kill switch block

    def test_openvpn_fallback_included_when_requested(self):
        cfg = build_vpn_configs("Remote (VPS)", "Both", server_host="198.51.100.1")
        assert "OpenVPN" in cfg and "443" in cfg

    def test_keys_are_placeholders_only(self):
        cfg = build_vpn_configs("Remote (VPS)", "WireGuard", server_host="198.51.100.1")
        # never emits real private key material — only placeholders + genkey hints
        assert "<SERVER_PRIVATE_KEY>" in cfg
        assert "wg genkey" in cfg
