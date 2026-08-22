# Sentinel — Manual Test Cases
**Type:** User Acceptance Testing (UAT)
**How to use:** Open the app, pick the agent, paste the input, then check the output against the "What to verify" list. Tick each box as you go.

---

## 1. Router Agent
> **What it does:** Automatically routes your input to the right agent based on keywords. Test this by watching *which agent gets triggered* when you type certain things.

**Test A — Routes to OSINT**
Input:
```
Look up the email suspect@darkmail.io
```
- [ ] App routes to / activates the OSINT agent (not Chat)

**Test B — Routes to Coding**
Input:
```
Debug this Python function for me
```
- [ ] App routes to the Coding agent

**Test C — Routes to Writing**
Input:
```
Write a cover letter for a software engineer position
```
- [ ] App routes to the Writing agent

**Test D — Falls back to Chat**
Input:
```
What is the speed of light?
```
- [ ] App routes to the Chat agent (default fallback)

---

## 2. Manager Agent
> **What it does:** Takes a plain-English agent idea and returns a structured JSON spec for it.

**Input:**
```
An agent that monitors Reddit and Hacker News for mentions of our product name and summarises the sentiment daily.
```
**What to verify:**
- [ ] Response is valid JSON (no markdown errors, properly formatted)
- [ ] `name` field is snake_case (e.g. `reddit_monitor_agent`)
- [ ] `system_prompt` field is detailed and relevant to the task
- [ ] `allowed_providers` makes sense (should include `openai` or similar, not just `ollama`)
- [ ] `budget_limit_eur` is set to a reasonable number (not null — this agent needs the internet)
- [ ] `reasoning` field explains the choices made

---

## 3. Chat Agent
> **What it does:** General-purpose conversation with no system prompt. Should feel like a clean, unfiltered chat.

**Input:**
```
Explain the difference between TCP and UDP like I'm 15 years old.
```
**What to verify:**
- [ ] Response is conversational and clear
- [ ] No structured sections/headers forced onto the reply (it's just chat)
- [ ] No system prompt artefacts bleeding into the reply

---

## 4. Coding Agent
> **What it does:** Coding assistant. Should explain, debug, and write code with practical clarity.

**Input:**
```
This function is supposed to return unique items from a list but it's not working right:

def get_unique(items):
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result

print(get_unique([1, 2, 2, 3, 1, 4]))  # Returns [1,2,3,4] — but what's wrong with this approach for large lists, and how would you fix it?
```
**What to verify:**
- [ ] Correctly identifies the O(n²) performance issue
- [ ] Suggests using a `set` or `dict` for O(n) performance
- [ ] Provides a corrected version of the function with code
- [ ] Explanation is clear, not just a code dump

---

## 5. Writing Agent
> **What it does:** Improves clarity, tone, and structure of existing text while preserving the original meaning.

**Input:**
```
Rewrite this email more professionally:

"hey so basically i wanted to let u know that the project is kinda behind schedule bc we had some issues with the api stuff and idk when its gonna be done tbh. sry about that"
```
**What to verify:**
- [ ] Tone is professional and clear
- [ ] Original meaning is fully preserved (delay, API issue, uncertainty on timeline)
- [ ] No information is added that wasn't in the original
- [ ] Length is appropriate (not bloated, not too short)

---

## 6. OSINT Agent (Light)
> **What it does:** Produces a structured OSINT analysis plan — query structure, Google dorks, public sources, and next steps. Does NOT make live lookups.

**Input (Email target):**
```
Target: darkweb_seller_99@protonmail.com
```
**What to verify:**
- [ ] Response has exactly four sections: **QUERY STRUCTURE**, **GOOGLE DORKS**, **PUBLIC SOURCES**, **SUMMARY & NEXT STEPS**
- [ ] Google Dorks section has 8–12 ready-to-paste search strings using operators like `site:`, `inurl:`, `"@"`
- [ ] Public Sources section names real, specific platforms (e.g. HaveIBeenPwned, Dehashed, LinkedIn)
- [ ] Summary gives 3–5 prioritised next steps
- [ ] Agent does NOT claim to have found real data about this email

**Bonus test — Username target (change query type dropdown if available):**
```
Target: h4x0r_pete99
Query type: Username
```
- [ ] Google Dorks are username-oriented (not domain/email dorks)
- [ ] Sources list includes social platforms and username-lookup tools

---

## 7. OSINT Heavy Agent
> **What it does:** Deep, structured investigation dossier with threat level, confidence score, and exhaustive section coverage.

**Input:**
```
Target: phishkit-delivery.ru
Target Type: Domain / IP
Scope: Deep Dive
Objective: Determine if this domain is part of active phishing infrastructure and identify any connected threat actors.
```
**What to verify:**
- [ ] Response contains all major sections (Overview, Digital Footprint, Infrastructure, Risk & Red Flags, etc.)
- [ ] **THREAT LEVEL: X/10** appears as a line in the overview
- [ ] **CONFIDENCE: X%** appears as a line in the overview
- [ ] **SOURCES REFERENCED: X** appears
- [ ] "Deep Dive" scope produces notably more detailed output than a Quick Scan would
- [ ] Response covers subdomains, WHOIS, certificate history, hosting patterns
- [ ] Agent does NOT invent real data — it describes what would be found and how to find it

**Bonus test — with image metadata:**
Paste the same input but also add this into the image metadata field (if available in the UI):
```
GPS: 48.8566° N, 2.3522° E | Device: iPhone 14 Pro | Date: 2024-11-03 | Software: Adobe Photoshop
```
- [ ] Response explicitly references the image metadata
- [ ] GPS coordinates are noted as a significant finding
- [ ] Photoshop metadata is flagged as a possible manipulation indicator

---

## 8. Author Agent
> **What it does:** Three modes — creative prose drafting, publishing documents (query letters, synopses), and book marketing copy.

**Test A — Creative Draft**
```
Write the opening scene of a psychological thriller. 
POV: first person. Setting: a rainy night, a woman receives a letter addressed to her dead sister. 
Tone: unsettling, literary. About 300 words.
```
- [ ] Response is formatted under a **[DRAFT]** header
- [ ] Written in first-person POV as specified
- [ ] Tone is atmospheric and tense, not generic
- [ ] Sensory details present (rain, physical sensation, etc.)

**Test B — Publishing Mode**
```
Write a query letter for my 85,000-word psychological thriller manuscript called "The Sister's Letter". It follows a woman who begins receiving letters from her dead sister and slowly unravels a 20-year-old family secret.
```
- [ ] Response is formatted as a professional query letter
- [ ] Includes hook, plot summary, word count, genre, and author sign-off
- [ ] Different style/format from the creative draft mode

**Test C — Marketing Mode**
```
Write an Instagram launch post for my debut thriller novel "The Sister's Letter" — psychological thriller, 85k words, launches next Tuesday.
```
- [ ] Response is short, punchy, Instagram-native (not a wall of text)
- [ ] Includes a hook, a hint of the premise, and a CTA
- [ ] Different tone from both the draft and the query letter

---

## 9. Bug Bounty Agent
> **What it does:** Analyses security findings and produces a structured vulnerability report + a ready-to-submit bug bounty write-up.

**Input:**
```
Program: HackerOne — AcmeCorp Web App
Scope: api.acmecorp.com
Target: GET /api/v2/invoices?user_id=1041

Finding:
By changing user_id from 1041 to 1040, 1039, etc. the API returns full invoice data for other users without any authorisation check. Tested 5 different IDs, all return distinct user data. No rate limiting observed.

HTTP Response (truncated):
{"invoice_id": "INV-9921", "user_id": 1040, "email": "bob@example.com", "amount": 349.00, "address": "12 Oak St, London"}

Nmap:
PORT    STATE SERVICE VERSION
443/tcp open  https   nginx/1.20.1
8443/tcp open  ssl/http nginx/1.20.1
```
**What to verify:**
- [ ] Vulnerability is correctly classified (IDOR — Insecure Direct Object Reference, CWE-639)
- [ ] Severity is rated High or Critical with a CVSS score
- [ ] Proof of Concept section has step-by-step reproduction steps
- [ ] Remediation section gives concrete developer-facing advice (not just "fix it")
- [ ] **SUBMISSION DRAFT** section is ready to paste into HackerOne (title, severity, description, PoC, impact)
- [ ] Nmap findings are referenced (open ports noted as attack surface)

---

## 10. Fiverr Agent
> **What it does:** Three modes — delivery message, gig description, DALL-E logo prompt.

**Brief to use for all three tests:**
```
Business name: NovaBrew Coffee
Industry: Specialty Coffee Shop
Style: Minimalist / Modern
Colors: Deep navy and warm gold
Notes: Premium artisan feel, not corporate. Target audience: 25–40 urban professionals.
```

**Test A — Delivery Message**
- Select task: "Write a delivery message"
- [ ] Response is warm and professional
- [ ] Under 200 words
- [ ] References the design choices made (navy/gold, minimalist)
- [ ] Offers a revision round

**Test B — Gig Description**
- Select task: "Write a Fiverr gig description"
- [ ] Has a hook headline as the opener
- [ ] Includes a bullet list of what the buyer gets
- [ ] Has Basic / Standard / Premium package breakdown
- [ ] Ends with a call to action
- [ ] Under 400 words

**Test C — Logo Prompt (DALL-E)**
- Use the image prompt button/mode
- [ ] Output is a single ready-to-paste prompt (no explanation text around it)
- [ ] Includes "vector logo, transparent background" or similar
- [ ] Describes navy and gold colour palette
- [ ] 1–3 sentences max

---

## 11. Health Agent
> **What it does:** Health & wellness advisor — gives structured action plans for fitness, nutrition, and lifestyle goals.

**Input:**
```
Goal: Lose 12 kg in 4 months.
Age: 32, female, 168 cm, 78 kg.
Activity level: Currently sedentary (desk job), want to start exercising.
Diet: No major restrictions, but I hate cooking elaborate meals. Vegetarian.
Medical: Mild hypothyroidism (on Levothyroxine). No other conditions.
```
**What to verify:**
- [ ] Response has all four sections: **SUMMARY**, **ACTION PLAN**, **DIET & LIFESTYLE**, **CAUTIONS**
- [ ] Action plan has 3–7 specific, prioritised steps with frequencies/durations
- [ ] Distinguishes quick wins (this week) from longer-term habits
- [ ] Vegetarian diet is respected in food recommendations
- [ ] Hypothyroidism is acknowledged in the Cautions section
- [ ] Medical disclaimer is present (⚠️ not medical advice)
- [ ] Does NOT prescribe medication or dosage changes

---

## 12. Investment Agent
> **What it does:** Market analysis across all asset classes — macro context, technical picture, price targets with bull/base/bear cases.

**Input:**
```
Analyse Bitcoin (BTC/USD) as of today.
Current price: ~$67,000. 
Macro context: Fed has paused rate hikes. ETF inflows have been strong. Halving occurred ~6 months ago.
Provide price targets with bull, base, and bear cases for the next 3 months.
```
**What to verify:**
- [ ] Response covers: **MARKET OVERVIEW**, **TECHNICAL PICTURE**, **MACRO & SECTOR CONTEXT**, **PRICE TARGETS**, **KEY RISKS**
- [ ] Price targets include three scenarios (bull/base/bear) with probabilities that add up sensibly
- [ ] Directional call is explicit: UP / DOWN / SIDEWAYS
- [ ] Conviction level is stated: Low / Medium / High
- [ ] Financial disclaimer appears at the bottom
- [ ] Does NOT skip the disclaimer

---

## 13. NFL Bet Agent
> **What it does:** Prop bet analyst — evaluates over/under props with structured over case, under case, edge assessment, and recommendation.

**Input:**
```
Prop: Josh Allen — Passing Yards OVER 267.5 (-115)
Week 9 vs. Indianapolis Colts (away game).
Season stats: 298 avg passing yards/game, 7 games.
vs Colts last 2 seasons: 312 yards, 287 yards.
Colts pass defense: 24th in yards allowed per game (247 avg).
Weather: Indoor stadium. No injury report concerns.
Josh Allen last 4 away games: 241, 305, 278, 319 yards.
```
**What to verify:**
- [ ] Response has all five sections: **PROP OVERVIEW**, **OVER CASE**, **UNDER CASE**, **EDGE ASSESSMENT**, **ACTIONABLE RECOMMENDATION**
- [ ] Uses the actual numbers provided (not generic analysis)
- [ ] Edge assessment gives a clear lean: OVER / UNDER / NO EDGE
- [ ] Suggests a unit size: 0 / 0.5 / 1 / 2
- [ ] EV calculation appears if odds are factored in
- [ ] Lists game-time factors to monitor before betting

---

## 14. ROI Agent
> **What it does:** Short-to-medium term opportunity analysis — bull case, bear case, ROI estimate, entry/exit strategy.

**Input:**
```
Asset: PLTR (Palantir Technologies) — currently at $21.50/share.
Catalyst: US Army AI contract renewal announcement expected within 2 weeks.
Sector: Defence tech / AI. Institutional accumulation visible on charts.
Timeframe: 3–4 weeks.
Capital available: $3,000.
```
**What to verify:**
- [ ] Response has: **OPPORTUNITY SUMMARY**, **BULL CASE**, **BEAR CASE**, **ROI ANALYSIS**, **ACTIONABLE RECOMMENDATION**
- [ ] ROI % is given as a realistic range (not just best case)
- [ ] Risk/reward ratio is calculated
- [ ] Entry strategy is specific (buy now vs. wait for pullback vs. scale in)
- [ ] Take profit levels and stop-loss level are given
- [ ] Financial disclaimer is present

---

## 15. Music Agent
> **What it does:** Full Spotify artist setup — bios, release metadata, playlist pitching, distributor guidance. Clearly marks AI-generated content vs. manual steps.

**Input:**
```
Artist name: NOVA//DRIFT
Genre: Indie Electronic / Ambient Pop
Location: Berlin, Germany
Similar artists: Bonobo, Tycho, Tourist
Debut EP: "Static Light" — 5 tracks, releasing in 3 weeks.
Track list: 1. Neon Pulse  2. Drift  3. Hollow Ground  4. Signal Loss  5. Static Light
No distributor yet. No Spotify profile yet.
```
**What to verify:**
- [ ] Response has **ARTIST PROFILE** section and **RELEASE SETUP** section
- [ ] Short bio is ≤ 150 characters (check this manually)
- [ ] Long bio is 300–500 words
- [ ] Track descriptions are written for all 5 tracks
- [ ] Distributor recommendation is made (DistroKid, TuneCore, or similar) with real pricing
- [ ] Content is clearly labelled **[AI OUTPUT — COPY-PASTE READY]** vs **[HUMAN ACTION REQUIRED]**
- [ ] Step-by-step manual instructions are included for the human steps

---

## 16. Webdesign Agent
> **What it does:** Generates complete, self-contained HTML/CSS/JS — no frameworks unless specified. Mobile-first, accessible, semantic.

**Input:**
```
Build a landing page for a freelance photographer called "Lens & Light Studio".
Sections: hero with full-screen background image placeholder, 3-column portfolio grid, an about section, and a contact form.
Style: dark background, cream and terracotta accents. Elegant and minimal.
No frameworks — vanilla HTML/CSS/JS only.
Make it responsive with a hamburger menu on mobile.
```
**What to verify:**
- [ ] Output is a single, complete HTML file (not separate CSS/JS files)
- [ ] Code uses semantic HTML5 tags (`<header>`, `<main>`, `<section>`, `<footer>`)
- [ ] CSS uses custom properties (variables) for colours
- [ ] Hamburger menu logic is included (JS toggle)
- [ ] Mobile responsive (check for `@media` queries or flexbox/grid)
- [ ] No jQuery, no external framework imports
- [ ] Paste the code into a browser — it renders without errors

---

## 17. WiFi Agent
> **What it does:** Analyses macOS Wi-Fi scan output — identifies security risks, adapter capabilities, and provides a structured security assessment.

**Input:**
```
macOS airport scan results:
SSID: HomeNetwork_2.4G    BSSID: A4:C3:F0:12:34:56  RSSI: -48  Channel: 6   Security: WPA2 Personal
SSID: HomeNetwork_5G      BSSID: A4:C3:F0:12:34:57  RSSI: -51  Channel: 36  Security: WPA2 Personal
SSID: NETGEAR_Open        BSSID: 2C:3A:FD:99:AA:BB  RSSI: -61  Channel: 11  Security: NONE
SSID: AndroidAP_F33A      BSSID: FA:11:22:33:44:55  RSSI: -72  Channel: 1   Security: WPA2 Personal
SSID: BT-BusinessHub      BSSID: 00:17:C4:00:11:22  RSSI: -80  Channel: 6   Security: WPA2 Enterprise

Interface: en0  Mode: Station  TX Rate: 867 Mbps
USB Adapter detected: 0bda:8812
```
**What to verify:**
- [ ] `NETGEAR_Open` (no security) is flagged as a risk
- [ ] `AndroidAP_F33A` is noted as a possible rogue hotspot / tethering device
- [ ] WPA2 Enterprise network is identified as the most secure
- [ ] USB adapter `0bda:8812` is recognised (RTL8812AU / AWUS036ACH — dual-band, monitor mode capable)
- [ ] Response includes a structured assessment — not just a raw list
- [ ] Recommendations are actionable (e.g. avoid open networks, enable WPA3 if available)

---

## 18. Audiobook Connector
> **What it does:** Parses a config block for the audiobook generator — validates required fields and applies defaults.

**Test A — Full config (all fields)**
```
input=/Users/andreas/Books/dune.epub
output=/Users/andreas/Audiobooks/dune/
voice=onyx
chunk_tokens=2000
```
- [ ] Job is accepted / starts without errors
- [ ] Voice is set to `onyx` (not the default `alloy`)
- [ ] Chunk size is `2000` (not the default `1500`)

**Test B — Minimal config (defaults)**
```
input=/Users/andreas/Books/foundation.epub
output=/Users/andreas/Audiobooks/foundation/
```
- [ ] Job is accepted
- [ ] Voice defaults to `alloy`
- [ ] Chunk tokens defaults to `1500`

**Test C — Missing `output` field (should error)**
```
input=/Users/andreas/Books/neuromancer.epub
voice=shimmer
```
- [ ] App shows an error message mentioning `output` is required
- [ ] Job does NOT start

**Test D — Missing `input` field (should error)**
```
output=/Users/andreas/Audiobooks/test/
```
- [ ] App shows an error message mentioning `input` is required
- [ ] Job does NOT start
