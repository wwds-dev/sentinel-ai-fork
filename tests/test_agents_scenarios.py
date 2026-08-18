"""
Sentinel AI — Agent Scenario Tests
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
from agents.author_agent       import AuthorAgent
from agents.bug_bounty_agent   import BugBountyAgent
from agents.fiverr_agent       import FiverrAgent
from agents.music_agent        import MusicAgent
from agents.webdesign_agent    import WebdesignAgent
from agents.wifi_agent         import WiFiAgent
from agents.audiobook_connector import AudiobookConnector


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
# 8. AuthorAgent
# Scenario: draft prose  |  publish query letter  |  marketing copy
# ─────────────────────────────────────────────────────────────────────────────

class TestAuthorAgent:
    agent = AuthorAgent()

    DRAFT_PROMPT = (
        "Write the opening scene of a cyberpunk thriller. "
        "POV: third-person limited. Setting: neon-lit Tokyo, 2089. "
        "Tone: tense and atmospheric."
    )
    PUBLISH_PROMPT = "Write a query letter for a 90,000-word cyberpunk thriller manuscript."
    MARKET_PROMPT  = "Write Instagram caption copy for the launch of my cyberpunk thriller."

    def test_draft_message_structure(self):
        msgs = self.agent.build_messages(self.DRAFT_PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_draft_prompt_preserved(self):
        msgs = self.agent.build_messages(self.DRAFT_PROMPT)
        assert "cyberpunk" in _user(msgs)

    def test_draft_system_prompt_contains_writing_principles(self):
        sys = _system(self.agent.build_messages(self.DRAFT_PROMPT))
        assert "DRAFT" in sys or "prose" in sys.lower()

    def test_publish_message_structure(self):
        msgs = self.agent.build_publish_messages(self.PUBLISH_PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_publish_system_prompt_is_different(self):
        draft_sys   = _system(self.agent.build_messages(self.DRAFT_PROMPT))
        publish_sys = _system(self.agent.build_publish_messages(self.PUBLISH_PROMPT))
        assert draft_sys != publish_sys

    def test_publish_system_prompt_mentions_publishing(self):
        sys = _system(self.agent.build_publish_messages(self.PUBLISH_PROMPT))
        assert "publishing" in sys.lower() or "query" in sys.lower() or "synopsis" in sys.lower()

    def test_market_message_structure(self):
        msgs = self.agent.build_market_messages(self.MARKET_PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_market_system_prompt_is_different_from_draft(self):
        draft_sys  = _system(self.agent.build_messages(self.DRAFT_PROMPT))
        market_sys = _system(self.agent.build_market_messages(self.MARKET_PROMPT))
        assert draft_sys != market_sys

    def test_market_system_prompt_mentions_marketing(self):
        sys = _system(self.agent.build_market_messages(self.MARKET_PROMPT))
        assert "marketing" in sys.lower() or "copy" in sys.lower() or "launch" in sys.lower()


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
# 10. FiverrAgent
# Scenario: delivery message  |  gig description  |  DALL-E logo prompt
# ─────────────────────────────────────────────────────────────────────────────

class TestFiverrAgent:
    agent = FiverrAgent()

    BRIEF = {
        "business_name": "NovaBrew Coffee",
        "industry":       "Specialty Coffee Shop",
        "style":          "Minimalist / Modern",
        "colors":         "Deep navy and warm gold",
        "notes":          "Should feel premium and artisan, not corporate",
    }

    def test_delivery_message_structure(self):
        msgs = self.agent.build_messages("Write a delivery message", self.BRIEF)
        assert _roles(msgs) == ["system", "user"]

    def test_brief_fields_in_user_message(self):
        msgs = self.agent.build_messages("Write a delivery message", self.BRIEF)
        user_text = _user(msgs)
        assert "NovaBrew Coffee" in user_text
        assert "Specialty Coffee Shop" in user_text
        assert "navy" in user_text.lower() or "Deep navy" in user_text

    def test_task_type_in_user_message(self):
        msgs = self.agent.build_messages("Write a delivery message", self.BRIEF)
        assert "delivery message" in _user(msgs).lower()

    def test_gig_description_task_in_user_message(self):
        msgs = self.agent.build_messages("Write a Fiverr gig description", self.BRIEF)
        assert "gig description" in _user(msgs).lower()

    def test_system_prompt_covers_all_three_modes(self):
        sys = _system(self.agent.build_messages("anything", self.BRIEF))
        assert "DELIVERY MESSAGE" in sys
        assert "GIG DESCRIPTION" in sys
        assert "LOGO PROMPT" in sys

    def test_image_prompt_request_structure(self):
        msgs = self.agent.build_image_prompt_request(self.BRIEF)
        assert _roles(msgs) == ["system", "user"]

    def test_image_prompt_request_mentions_dalle(self):
        msgs = self.agent.build_image_prompt_request(self.BRIEF)
        assert "DALL-E" in _user(msgs) or "dall-e" in _user(msgs).lower()

    def test_image_prompt_request_includes_brief(self):
        msgs = self.agent.build_image_prompt_request(self.BRIEF)
        assert "NovaBrew Coffee" in _user(msgs)



# ─────────────────────────────────────────────────────────────────────────────
# 15. MusicAgent
# Scenario: full Spotify artist setup for an indie electronic artist
# ─────────────────────────────────────────────────────────────────────────────

class TestMusicAgent:
    agent = MusicAgent()

    PROMPT = (
        "Artist name: NOVA//DRIFT\n"
        "Genre: Indie Electronic / Ambient Pop\n"
        "Location: Berlin, Germany\n"
        "Similar artists: Bonobo, Tourist, Tycho\n"
        "First release: debut EP 'Static Light' — 5 tracks, release date in 3 weeks.\n"
        "Set up my complete Spotify profile and release."
    )

    def test_message_structure(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_prompt_preserved(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "NOVA//DRIFT" in _user(msgs)
        assert "Static Light" in _user(msgs)

    def test_system_prompt_contains_output_sections(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        for section in ["ARTIST PROFILE", "RELEASE SETUP"]:
            assert section in sys

    def test_system_prompt_marks_ai_output_vs_human_steps(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "AI OUTPUT" in sys
        assert "HUMAN ACTION" in sys

    def test_system_prompt_mentions_bio_length_constraints(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        # Both short bio (150 chars) and long bio (300-500 words) should be referenced
        assert "150" in sys
        assert "300" in sys or "500" in sys


# ─────────────────────────────────────────────────────────────────────────────
# 16. WebdesignAgent
# Scenario: SaaS landing page with hero, features, pricing, CTA
# ─────────────────────────────────────────────────────────────────────────────

class TestWebdesignAgent:
    agent = WebdesignAgent()

    PROMPT = (
        "Build a SaaS landing page for a project management tool called 'Taskly'.\n"
        "Sections: hero with CTA, 3-feature grid, pricing table (3 tiers), footer.\n"
        "Style: clean, modern, dark mode. Colours: indigo and white. No frameworks.\n"
        "Include a mobile hamburger menu."
    )

    def test_message_structure(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert _roles(msgs) == ["system", "user"]

    def test_prompt_preserved(self):
        msgs = self.agent.build_messages(self.PROMPT)
        assert "Taskly" in _user(msgs)
        assert "hamburger" in _user(msgs).lower()

    def test_system_prompt_requires_semantic_html(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "semantic" in sys.lower() or "<header>" in sys or "HTML5" in sys

    def test_system_prompt_requires_responsive_css(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "responsive" in sys.lower() or "mobile" in sys.lower()

    def test_system_prompt_mentions_accessibility(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "accessibility" in sys.lower() or "aria" in sys.lower() or "alt" in sys.lower()

    def test_system_prompt_bans_jquery(self):
        sys = _system(self.agent.build_messages(self.PROMPT))
        assert "jQuery" in sys or "vanilla" in sys.lower()


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
# 18. AudiobookConnector
# Scenario A: full valid config  |  B: minimal valid  |  C/D: missing required fields
# ─────────────────────────────────────────────────────────────────────────────

class TestAudiobookConnector:
    connector = AudiobookConnector()

    def test_full_config_parses_correctly(self):
        text = (
            "input=/books/the_great_gatsby.epub\n"
            "output=/audiobooks/gatsby/\n"
            "voice=onyx\n"
            "chunk_tokens=2000"
        )
        config = self.connector.parse_input(text)
        assert config["input"]        == "/books/the_great_gatsby.epub"
        assert config["output"]       == "/audiobooks/gatsby/"
        assert config["voice"]        == "onyx"
        assert config["chunk_tokens"] == "2000"

    def test_minimal_config_parses_correctly(self):
        text = (
            "input=/books/dune.epub\n"
            "output=/audiobooks/dune/"
        )
        config = self.connector.parse_input(text)
        assert config["input"]  == "/books/dune.epub"
        assert config["output"] == "/audiobooks/dune/"

    def test_minimal_config_uses_default_voice(self):
        text = "input=/books/dune.epub\noutput=/audiobooks/dune/"
        config = self.connector.parse_input(text)
        assert config["voice"] == "alloy"   # default from __init__

    def test_minimal_config_uses_default_chunk_tokens(self):
        text = "input=/books/dune.epub\noutput=/audiobooks/dune/"
        config = self.connector.parse_input(text)
        assert config["chunk_tokens"] == 1500   # default from __init__

    def test_missing_input_raises_value_error(self):
        text = "output=/audiobooks/dune/"
        with pytest.raises(ValueError, match="input"):
            self.connector.parse_input(text)

    def test_missing_output_raises_value_error(self):
        text = "input=/books/dune.epub"
        with pytest.raises(ValueError, match="output"):
            self.connector.parse_input(text)

    def test_empty_string_raises_value_error(self):
        with pytest.raises(ValueError):
            self.connector.parse_input("")

    def test_extra_whitespace_around_values_is_stripped(self):
        text = "input = /books/dune.epub\noutput = /audiobooks/dune/"
        config = self.connector.parse_input(text)
        assert config["input"]  == "/books/dune.epub"
        assert config["output"] == "/audiobooks/dune/"
