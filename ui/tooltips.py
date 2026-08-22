"""Tooltip text for every control in the app.

Moved verbatim out of main.py (see docs/refactor_plan.md, phase 1) — the body
is unchanged apart from the receiver being named `app`, so the section comments
and the
order the tooltips are applied in are preserved exactly.
"""


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
        "docs_btn":                "Open the full Sentinel documentation.",
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
    # Reuse agent_subtitles dict — set each agent button's tooltip to its description
    subtitles_for_buttons = {
        "chat":        "General-purpose conversation. Pick a tool, pick a model, talk.",
        "osint":       "Light OSINT — structured research queries.",
        "osint_heavy": "Deep OSINT investigation with five-section dossier.",
        "wifi":        "Wireless recon, signal analysis, Kali command generation.",
        "bug_bounty":  "Vulnerability triage + HackerOne-ready submission drafts.",
        "nfl_bet":     "NFL prop bet analysis with EV and projection modelling.",
        "fiverr":      "Logo gigs — DALL·E prompts, gig descriptions, delivery messages.",
        "health":      "Nutrition, fitness, mental wellness guidance.",
        "author":      "Long-form fiction drafting and book writing.",
        "music":       "Spotify artist setup, distribution, income roadmap.",
        "webdesign":   "Modern HTML / CSS / JavaScript generation.",
        "audiobook":   "Convert ebooks (PDF / EPUB / TXT / MOBI) into MP3 audiobooks.",
        "manager":     "Describe a new agent in plain language — Forge writes the code.",
    }
    if hasattr(app, "agent_buttons"):
        for name, tip in subtitles_for_buttons.items():
            btn = app.agent_buttons.get(name)
            if btn is not None:
                btn.setToolTip(tip)
    app._set_tooltips({
        "history_search":   "Filter saved chats by typing here.",
        "history_list":     "Click a saved chat to re-open it.",
        "delete_chat_btn":  "Delete the currently selected saved chat.",
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


    # NFL Props (Playmaker)
    app._set_tooltips({
        "nfl_bet_player_input":   "Player or team the prop is on.",
        "nfl_bet_prop_type_box":  "Which prop you're evaluating (Passing Yards, Receptions, etc.).",
        "nfl_bet_line_input":     "The sportsbook line (e.g. 252.5).",
        "nfl_bet_odds_input":     "American odds for the side you're considering (e.g. -110).",
        "nfl_bet_context_input":  "Game context: opponent, week, weather, injuries.",
        "nfl_bet_data_input":     "Paste raw stats / game logs / matchup data. The agent works from what you provide — it has no live data feed.",
        "nfl_bet_analyse_btn":    "Run the prop bet analysis.",
        "nfl_bet_stop_btn":       "Cancel the analysis.",
        "nfl_model_player_input": "Player for season-long projection modelling.",
        "nfl_model_stat_box":     "Stat category to project.",
        "nfl_model_line_input":   "Optional prop line to evaluate against the projection.",
        "nfl_model_log_input":    "Paste the player's season game log (numbers per game).",
        "nfl_model_context_input":"Upcoming game context: opponent, week, weather, injuries.",
        "nfl_model_build_btn":    "Compute season stats and project the next game.",
        "nfl_model_stop_btn":     "Cancel the projection.",
    })

    # Health (Vitality)
    app._set_tooltips({
        "health_category_box":   "Health domain — nutrition, fitness, mental, weight management, etc.",
        "health_goal_box":       "Primary goal for this consultation.",
        "health_activity_box":   "Current activity level — affects calorie / training recommendations.",
        "health_age_input":      "Optional — your age, helps tailor advice.",
        "health_query_input":    "Describe your question, goal, or concern in detail.",
        "health_provider_box":   "Provider for the analysis call.",
        "health_model_box":      "Specific model.",
        "health_analyse_btn":    "Generate the four-section wellness plan.",
        "health_stop_btn":       "Cancel the request.",
        "health_help_btn":       "Open the Vitality documentation section.",
        "health_save_btn":       "Save the response to a .txt file.",
        "health_clear_btn":      "Clear the form and tabs.",
        "health_conf_label":     "Model's stated confidence in its recommendations.",
    })

    # Music (Maestro)
    app._set_tooltips({
        "music_provider_box":  "Provider for the analysis call.",
        "music_model_box":     "Specific model. Claude works best for long structured plans.",
        "music_analyse_btn":   "Generate the full five-section release plan.",
        "music_stop_btn":      "Cancel the request.",
        "music_help_btn":      "Open the Maestro documentation section.",
        "music_save_btn":      "Save the full plan as a .txt file.",
    })

    # Author (Manuscript)
    app._set_tooltips({
        "author_write_btn":    "Generate the requested writing (outline / characters / scene / world).",
        "author_continue_btn": "Continue from the last draft.",
        "author_save_btn":     "Save the current draft to disk.",
        "author_clear_btn":    "Clear the draft area and reset the form.",
    })

    # Web Design (Site Builder)
    app._set_tooltips({
        "webdesign_brief_input":  "Describe the page / component / layout you want generated.",
        "webdesign_provider_box": "Provider for the generation call.",
        "webdesign_model_box":    "Specific model.",
        "webdesign_generate_btn": "Generate the HTML / CSS / JS code.",
        "webdesign_stop_btn":     "Cancel the generation.",
        "webdesign_save_btn":     "Save the generated code as a .html file.",
    })

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

    # Fiverr (Atelier)
    app._set_tooltips({
        "fiverr_provider_box":     "Provider for text generation (delivery / gig description / prompts).",
        "fiverr_model_box":        "Specific model for text.",
        "fiverr_generate_btn":     "Build a DALL·E logo prompt from the brief, then generate the logos.",
        "fiverr_delivery_btn":     "Write a Fiverr delivery message based on the brief.",
        "fiverr_gig_btn":          "Write a full Fiverr gig description.",
        "fiverr_stop_btn":         "Cancel the running generation.",
        "fiverr_save_images_btn":  "Save all generated logo images to disk.",
        "fiverr_clear_btn":        "Clear the brief and outputs.",
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

    # Audiobook (Narrator)
    app._set_tooltips({
        "audiobook_book_list":      "Books found in the configured input folder. Click one to select.",
        "audiobook_refresh_btn":    "Rescan the input folder for new books.",
        "audiobook_start_btn":      "Start converting the selected book to MP3 via OpenAI TTS.",
        "audiobook_input_path":     "Folder where input ebooks live.",
        "audiobook_output_path":    "Folder where generated MP3 files are saved.",
        "audiobook_voice_box":      "OpenAI TTS voice to use.",
        "audiobook_chunk_input":    "Tokens per TTS chunk. Higher = fewer API calls; lower = safer for limits.",
        "tool_progress":            "Conversion progress.",
        "audiobook_status_label":   "Current conversion status.",
        "stop_btn":                 "Stop the running conversion.",
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
