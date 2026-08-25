# TRACE — Light OSINT

`key: osint` · class: `agents/osint_agent.py → OSINTAgent` · panel: `ui/panels/osint.py → OsintPanel`

## What it does
A fast, lightweight open-source-intelligence assistant. Given a target (name, username, email, domain, org) plus optional context, it structures a research query, suggests public sources and search operators, and summarises what to look for. It is a **reasoning/planning layer** — it does not perform live lookups itself.

## Inputs (panel controls)
| Control | Purpose |
|---|---|
| Query / target box | The subject to research. Structured types are validated locally before authorization. |
| Query type | Auto-detect, Person, Username, Email, Domain, Company, Phone, or IP Address. Auto-detect records the resolved type in the activity trail. |
| Model override | Optional provider/model change; the task recommendation is selected by default. |
| Structure Query | Generate a model-based investigation plan without contacting research sources. |
| Live Research | After explicit confirmation, query WHOIS/DNS/crt.sh for domains and IPs, URLScan for usernames, or individually selected email services. |
| Stop | Request cancellation; completed source results remain visible as a partial result. |

## Outputs
The persistent **Activity** trail explains validation, local/cloud execution,
model processing, completion, cancellation, and errors. It explicitly states
whether external sources were queried and remains visible after completion.
Results are shown as readable cards, with the raw streamed response visible
while generation is in progress.

Successful runs appear in Trace's **Saved Searches** rail. A saved search can be
filtered, reopened, renamed, deleted, or used as the starting point for a new
search. Reopening restores the target, query type, provider/model where
available, and structured response without performing another request.

**Live Research** results are collected records rather than model
inferences. The Activity trail names each source as it is contacted, records
success or failure independently, and lists the sources actually contacted at
completion. One failed source does not discard successful results.

For email targets, the complete address is sent only to sources selected in the
confirmation dialog. EmailRep is selected by default; Have I Been Pwned and
BreachDirectory are off by default. HIBP cannot be selected without a configured
API key. A service skipped before contact is recorded separately and is not
reported as contacted.

## How it works
`OSINTAgent.validate_target()` validates and classifies the target entirely
offline. `build_messages()` then wraps the accepted target in a system prompt
tuned for defensive, legal OSINT. Requests run through the shared `ChatWorker`,
request guard, cost tracking, history, and run logger.

## Under the hood — files & functions
| Location | Role |
|---|---|
| `agents/osint_agent.py` | `OSINTAgent` — system prompt + message builder. |
| `ui/panels/osint.py` | Panel, workflow state, result presentation, and request lifecycle. |
| `main.py` | Routing, authorization, Saved Searches, history, and provider execution. |
| `providers/domain_lookup.py` | Consented live WHOIS, DNS, and certificate-transparency collection for domains/IPs. |
| `providers/username_lookup.py` | Consented URLScan search for public pages containing a username. |
| `providers/email_lookup.py` | Per-source EmailRep, HIBP, and BreachDirectory collection with breach services opt-in. |

## Extend it
- **People/company/phone enrichment (not implemented)**: evaluate lawful sources and source-specific privacy implications before adding collectors. Do not silently add network collection to Structure Query.
- **Escalation**: hand results to **Bloodhound** (`osint_heavy`) for a full dossier.
- Edit the system prompt in `agents/osint_agent.py` to change tradecraft focus.

## Requirements
Any model provider (API key and consent for cloud; Ollama is local and free).
HIBP requires `HIBP_API_KEY`; its checkbox is unavailable without one. EmailRep,
BreachDirectory, URLScan, WHOIS, the configured DNS resolver, and crt.sh can be
used without a configured application key, subject to their own limits and
availability. Structure Query never contacts these services.
