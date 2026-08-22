# Sentinel agent development tracks

Sentinel v2 is the shared baseline. Further work should branch from this point
by agent, not by copying the whole platform into separate implementations. Each
track owns its domain behaviour and UI; provider access, request guarding,
projects, usage, costs, history, run logging, retries and common widgets remain
shared platform code.

## Definition of v2 for every track

An agent is at v2 only when all of these are true:

- its primary job works end to end with local and permitted cloud providers;
- inputs are validated and dangerous or out-of-scope actions fail closed;
- every paid request uses the shared authorization, budget, usage and run log;
- output is structured, actionable, exportable and useful without reading raw
  model prose;
- secrets and sensitive targets are redacted from logs and saved artifacts;
- cancellation, provider failure and malformed model output recover cleanly;
- unit tests cover parsing and policy, an offscreen UI test covers layout, and
  the packaged app smoke test passes.

## Track A — Chat and Projects

Current v2 baseline: streaming chat, provider routing, Saved Chats, project
grouping, project instructions/defaults/budgets and exact usage accounting.

Next improvements:

1. Continue a reopened conversation with its previous messages, with a visible
   context/token preview before sending.
2. Add project knowledge files using local extraction, chunking and citations.
3. Export a complete run as Markdown: messages, model, usage, cost and project.
4. Add a deliberate Ollama fallback option when a cloud budget is exhausted.

## Track B — Trace

Current v2 baseline: lightweight OSINT workflow with guarded requests and
structured identity, footprint, risk and next-step sections.

Next improvements:

1. Attach provenance to every factual claim (source URL, retrieval time and
   confidence) and separate observation from model inference.
2. Add entity resolution and duplicate detection across names, usernames,
   domains and email addresses.
3. Produce a compact evidence bundle and a redacted shareable report.
4. Add target-consent/scope presets and retention controls.

## Track C — Bloodhound

Current v2 baseline: deep multi-source dossier, image metadata input, risk
indicators and structured section cards.

Next improvements:

1. Build an evidence graph linking people, organisations, infrastructure and
   breaches, with confidence and contradiction flags.
2. Resume long investigations from checkpoints instead of restarting them.
3. Add source freshness, stale-evidence warnings and claim-level citations.
4. Encrypt sensitive case exports and support case-level retention limits.

## Track D — Beacon

Current v2 baseline: adapter diagnostics, authorised wireless analysis,
AI-assisted explanation and Kali/aircrack command generation.

Next improvements:

1. Separate read-only diagnostics from active test commands and require a clear
   second approval for deauthentication, capture or injection operations.
2. Detect interface capabilities and operating-system support before proposing
   commands.
3. Parse command results into channel congestion, signal quality and remediation
   recommendations rather than leaving raw terminal output.
4. Add a lab-mode simulator so workflows can be learned without a live target.

## Track E — Bug Spray

Current v2 baseline: authorised bug-bounty analysis, PoC, remediation and
submission-draft sections.

Next improvements:

1. Import program scope/rules and block suggestions outside allowed assets or
   prohibited vulnerability classes.
2. Add reproducibility checks, CVSS reasoning and evidence completeness gates.
3. Deduplicate findings and track their lifecycle from suspected to triaged,
   reported, fixed and retested.
4. Export platform-ready HackerOne/Bugcrowd reports with sensitive data removed.

## Track F — Tunnel

Current v2 baseline: self-hosted WireGuard/OpenVPN guidance, guarded requests,
offline configuration builder and structured runbook output.

Next improvements:

1. Validate generated configs locally before display or export and refuse weak
   keys, unsafe routes, DNS leaks and non-fail-closed rules.
2. Never persist private keys in chat history or logs; add automatic redaction
   tests for all config formats.
3. Add a connectivity/leak diagnostic with a reversible change plan.
4. Generate rollback instructions beside every deployment step.

## Track G — Forge

Current v2 baseline: agent specification analysis, permissions/controls review,
structured spec display and approved file generation.

Next improvements:

1. Show a complete file diff and test plan before approval; default to dry-run.
2. Validate generated agents against the host protocol, registry schema,
   request guard and packaging rules automatically.
3. Create changes on a dedicated branch/worktree with a one-click rollback.
4. Add security review for prompts, permissions, filesystem access and secrets.

## Fork and merge order

1. Tag the shared baseline `sentinel-v2` after packaging verification.
2. Create one worktree/branch per track: `track/chat`, `track/trace`,
   `track/bloodhound`, `track/beacon`, `track/bug-spray`, `track/tunnel` and
   `track/forge`.
3. Land shared-platform fixes first; rebase the agent tracks before their final
   verification so money/security logic never forks permanently.
4. Merge one track at a time only after its v2 definition passes. Run the full
   suite and packaged smoke test after every merge.
5. Keep external standalone apps as thin shells over shared packages; do not
   copy provider, budget or usage code into them.

Recommended order is Chat/Projects → Forge → Tunnel → Bug Spray → Trace →
Bloodhound → Beacon. That strengthens the shared context and generation
foundation first, then the highest-risk security workflows, before deeper
research and hardware-specific work.
