# Sentinel — Suggestions

Ideas not yet committed to. Status: `IDEA` · `CONSIDERING` · `PLANNED` · `DONE` · `REJECTED`

---

## v2 — in the current arc

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 1 | Finish the `main.py` split — Phase 3 `AgentHost` protocol + `AgentPanel` base, then one module per agent panel | design | L | DONE |
| 2 | Key `_pending_requests` by run-id instead of agent name, so two runs of the same agent can't clobber each other's context | bug | S | DONE |
| 3 | Remove the dead `ops_identity` sidebar entry — listed in `agent_titles` with no implementation behind it | bug | XS | DONE |
| 4 | Kimi prompt caching in the pricing model — cached input is billed differently | feature | M | DONE |
| 5 | Budget card layout — session, daily and active-project progress meters | design | S | DONE |
| 6 | Per-agent cost breakdown in the cost dialog, so it's visible which agent is eating the daily cap | feature | M | IDEA |

## v3 — bigger swings

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 7 | Streaming responses in the chat panel rather than wait-then-dump | feature | L | IDEA |
| 8 | Local model provider (Ollama) as a zero-cost fallback when the budget cap is hit | feature | L | IDEA |
| 9 | Retry-with-backoff wrapper shared by every provider client, instead of per-client handling | infra | M | IDEA |
| 10 | Export a run (prompt + response + usage + cost) as a single markdown file for archiving | feature | S | IDEA |

## Done

| Suggestion | When |
|---|---|
| Saved Chats: agent filter and rename | Aug 2026 |
| `authorize_request` / `record_request` guard applied to all 19 unguarded `ChatWorker` sites | Aug 2026 |
| `FlowLayout` on 13 control rows — panels no longer crush when narrow | Aug 2026 |
| Timeouts on all cloud clients | Aug 2026 |
| Phase 1+2 of the refactor: `ui/workers.py`, `ui/widgets.py`, `ui/style.py`, `ui/tooltips.py`, `ui/dialogs.py` | Aug 2026 |
| Phase 3+4 of the refactor: host protocol, panel base and six standalone panel modules | Aug 2026 |
| Request contexts keyed by unique run id | Aug 2026 |
| Resource monitor degrades gracefully when a macOS statistic is unavailable | Aug 2026 |
| Exact decimal budget-boundary comparisons | Aug 2026 |
| Chat Projects Stage 2: grouping, instructions, defaults and budgets | Aug 2026 |
| Product rename to Sentinel with safe legacy-data migration | Aug 2026 |

## Rejected

| Suggestion | Why |
|---|---|
| Fork the ROI / investment agents back in | They moved to SONAR on purpose; two homes for the same logic is worse than one |
