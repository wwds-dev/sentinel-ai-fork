"""Tooltip text for every control in the app.

Moved verbatim out of main.py (see docs/refactor_plan.md, phase 1) — the body
is unchanged apart from the receiver being named `app`, so the section comments
and the
order the tooltips are applied in are preserved exactly.
"""

from services.agent_catalog import BUILTIN_AGENTS


def seed_tooltips(app):
    """Apply explanatory tooltips to every important control in every
    panel. Tooltips can be toggled off via the chip in the header bar."""
    # ── Centre-panel general controls (Chat / normal panel) ──────────
    app._set_tooltips({
        "tool_box":                "System prompt frame applied to the conversation (General Chat, Writing, Coding, Summarize, Rewrite).",
        "command_box":             "Pre-built prompt scaffold from config/commands.json. Pick one or type your own message.",
        "provider_box":            "AI provider that will run this request. Ollama is local & free; Anthropic / OpenAI / DeepSeek / Gemini are cloud (pay-as-you-go).",
        "model_box":               "Specific model under the chosen provider. Larger models cost more but produce stronger output.",
        "refresh_models_btn":      "Re-fetch the model list from the selected provider.",
        "model_guide_btn":         "Open the in-app Model Guide with current models, pricing, and recommendations.",
        "docs_btn":                "Open the full Sentinel Fork documentation.",
        "agent_docs_btn":          "Open the documentation for the currently active agent.",
        "execution_mode_box":      "Local-only: only Ollama. Hybrid: pick best of local/cloud. Cloud-only: only paid providers.",
        "allow_openai_checkbox":   "Allow this request to use the OpenAI API (paid).",
        "allow_deepseek_checkbox": "Allow this request to use the DeepSeek API (paid, cheap).",
        "allow_kimi_checkbox": "Allow this request to use the Kimi API (paid, strong at coding/agentic tasks).",
        "allow_gemini_checkbox":   "Allow this request to use Google Gemini (free tier available).",
        "allow_anthropic_checkbox":"Allow this request to use Anthropic Claude (paid).",
        "input_box":               "Type your prompt here. Long prompts cost more on paid providers.",
        "send_btn":                "Send the prompt to the selected provider and model.",
        "stop_chat_btn":           "Cancel the in-flight request.",
        "auto_route_btn":          "Let the router pick the best agent + provider + model automatically.",
        "recommend_setup_btn":     "Apply the recommended provider + model for the current tool / agent.",
        "auto_recommend_checkbox": "Apply the recommendation automatically on every input change.",
        "estimate_btn":            "Show the estimated cost of the current prompt + settings before sending.",
        "export_btn":              "Export the last response to a Markdown / HTML report.",
        "tooltips_toggle_btn":     "Toggle hover tooltips across the entire app.",
        "agent_title_label":       "Current agent. Click an agent in the left sidebar to switch.",
        "agent_subtitle_label":    "What this agent does in one line.",
        "agent_status_pill":       "Current agent status. ●  READY = idle; flips colour when a request is running or has errored.",
    })

    # ── Left panel ───────────────────────────────────────────────────
    if hasattr(app, "agent_buttons"):
        for name, metadata in BUILTIN_AGENTS.items():
            btn = app.agent_buttons.get(name)
            if btn is not None:
                btn.setToolTip(metadata["tooltip"])
    app._set_tooltips({
        "history_search":   "Filter saved chats by typing here.",
        "history_list":     "Click a saved chat to re-open it.",
        "delete_chat_btn":  "Delete the currently selected saved chat.",
        "saved_search_search": "Filter saved Trace searches by target or result text.",
        "saved_search_list": "Click a saved search to restore its target and results.",
        "delete_search_btn": "Delete the currently selected saved Trace search.",
        "new_search_btn": "Clear Trace and begin a new search.",
        "new_chat_btn":     "Start a fresh conversation (clears the current context).",
    })

    # ── Right panel cards ────────────────────────────────────────────
    app._set_tooltips({
        "resource_label":           "Live RAM / CPU / SWAP / battery snapshot. Green = healthy, yellow = busy, red = stressed.",
        "realtime_monitor_btn":     "(Coming soon) Live charts of system resource usage.",
        "route_result_label":       "Last routing decision — which agent + provider + model was used.",
        "recommendation_label":     "Recommendation for the current tool / agent — provider + model + reason.",
        "live_estimate_label":      "Estimated cost of the current prompt at the selected provider + model.",
        "last_request_label":       "Cost of the most recently completed request.",
        "session_cost_label":       "Total spend since this app session started.",
        "today_cost_label":         "Total spend today (resets at midnight local time).",
        "request_count_label":      "Number of requests sent today and during this session.",
        "budget_label":             "How much of the budget remains for this session and today.",
        "session_budget_input":     "Maximum spend allowed for this session in euros.",
        "daily_budget_input":       "Maximum spend allowed per day in euros.",
        "save_budget_btn":          "Persist the budget limits to settings.",
        "reset_session_budget_btn": "Reset the session spend counter back to zero.",
        "cost_history_btn":         "Open the Cost History dialog (charts and tables of past spending).",
        "run_log_btn":              "Open the Run Log dialog (every request with status, duration, cost).",
        "settings_btn":             "Open the Settings dialog (pricing, agents, tools, EUR/USD rate).",
        "openai_key_label":         "Whether an OpenAI API key is configured. Set OPENAI_API_KEY in .env or ~/.zshrc.",
        "deepseek_key_label":       "Whether a DeepSeek API key is configured. Set DEEPSEEK_API_KEY in .env or ~/.zshrc.",
        "kimi_key_label":           "Whether a Kimi (Moonshot AI) API key is configured. Set KIMI_API_KEY in .env or ~/.zshrc.",
        "gemini_key_label":         "Whether a Google Gemini API key is configured. Set GOOGLE_API_KEY in .env or ~/.zshrc.",
        "anthropic_key_label":      "Whether an Anthropic API key is configured. Set ANTHROPIC_API_KEY in .env or ~/.zshrc.",
    })

    # ── Per-agent panel tooltips ─────────────────────────────────────


    # Wi-Fi (Beacon)
    app._set_tooltips({
        "wifi.mode_box":          "What to run — Interface Info, Scan Networks, Signal Monitor, Ping Test, or Kali Command Builder.",
        "wifi.interface_box":     "Which network interface to use (typically en0 on Mac).",
        "wifi.target_input":      "Target host (only used by Ping Test mode).",
        "wifi.run_btn":           "Run the selected mode.",
        "wifi.stop_btn":          "Cancel the running scan / probe.",
        "wifi.help_btn":          "Open the Beacon documentation section.",
        "wifi.detect_btn":        "Scan USB for known compatible Wi-Fi adapters (TL-WN722N, AWUS036ACH, etc.).",
        "wifi.save_btn":          "Save the raw output to a file.",
    })

    # OSINT (Trace) — moved to ui/panels/osint.py, so the names are dotted.
    app._set_tooltips({
        "osint.target_input":   "What you want to research — name, handle, domain, email, etc.",
        "osint.type_box":       "Narrow the search to one kind of identifier, or let Trace detect it.",
        "osint.provider_box":   "Provider for the analysis call.",
        "osint.model_box":      "Specific model.",
        "osint.analyse_btn":    "Run the structured OSINT query.",
        "osint.stop_btn":       "Cancel the analysis.",
    })

    # OSINT Pro (Bloodhound)
    app._set_tooltips({
        "osint_heavy.target_input":     "Target identifier (person, username, domain, IP, organisation).",
        "osint_heavy.type_box":         "Target type — guides which tools and pivots are used.",
        "osint_heavy.scope_box":        "Investigation depth: Quick Scan / Standard / Deep Dive.",
        "osint_heavy.objective_input":  "Investigation objective / context for the analyst.",
        "osint_heavy.browse_btn":      "Optional — image to extract EXIF metadata from.",
        "osint_heavy.investigate_btn":  "Generate the five-section investigation dossier.",
        "osint_heavy.stop_btn":         "Cancel the investigation.",
        "osint_heavy.save_btn":         "Save the full dossier to a .txt file.",
        "osint_heavy.threat_bar":       "Threat level on a 0–10 scale, extracted from the dossier.",
    })

    # Bug Bounty (Bug Spray)
    app._set_tooltips({
        "bug_bounty.target_input":       "Target asset in scope of the bug bounty program.",
        "bug_bounty.program_input":      "Name of the bug bounty program (HackerOne, Bugcrowd, etc.).",
        "bug_bounty.scope_box":          "Scope category — Web, Mobile, API, Network, etc.",
        "bug_bounty.findings_input":     "Paste raw findings: HTTP responses, Burp output, source snippets, recon notes.",
        "bug_bounty.nmap_cmd_input":     "Nmap command to run (will execute via subprocess locally).",
        "bug_bounty.nmap_run_btn":       "Run the Nmap command and capture output below.",
        "bug_bounty.nmap_stop_btn":      "Kill the running Nmap process.",
        "bug_bounty.nmap_output":        "Live Nmap subprocess output.",
        "bug_bounty.analyse_btn":        "Produce a CWE-classified vulnerability report and HackerOne-ready submission.",
        "bug_bounty.stop_btn":           "Cancel the analysis.",
        "bug_bounty.save_btn":           "Save the full report to a .txt file.",
        "bug_bounty.clear_btn":          "Clear inputs and outputs.",
    })

    # Manager (Forge)
    app._set_tooltips({
        "manager.idea_input":   "Describe the agent you want to create in plain language.",
        "manager.provider_box": "Provider used to generate the agent spec.",
        "manager.model_box":    "Specific model.",
        "manager.analyze_btn":  "Analyse the idea and produce a JSON spec for review.",
        "manager.clear_btn":    "Clear the form.",
        "manager.spec_display": "The generated spec — review before approving.",
        "manager.approve_btn":  "Approve the spec — Forge will write the agent code and register it.",
        "manager.reject_btn":   "Reject the spec and clear it.",
        "manager.log":          "Log of spec generation, approval, and file creation events.",
    })
