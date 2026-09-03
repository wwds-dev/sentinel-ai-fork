# Sentinel Fork — Suggestions

Ideas not yet committed to. Status: `IDEA` · `CONSIDERING` · `PLANNED` · `DONE` · `REJECTED`

---

## v2 — in the current arc

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 5 | Budget card layout — the €1 session / €5 daily figures deserve a progress bar, not two labels | design | S | CONSIDERING |
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
| Agent panel split: shared `AgentHost`, `AgentPanel`, and specialist panel modules | Aug 2026 |
| Canonical seven-agent roster; removed dead `ops_identity` sidebar entry | Aug 2026 |
| UI modules: workers, widgets, style, tooltips, and dialogs | Aug 2026 |
| Key `_pending_requests` by request id instead of agent name — two runs of the same agent no longer clobber each other's context | Sep 2026 |
| Kimi prompt caching modelled in the pricing table — cached input billed at ~20% of the base rate ($0.19/1M) | Sep 2026 |
| Auto-route button on every agent panel, applying the router's recommendation directly | Sep 2026 |
| Paid-route highlighting — any non-Ollama provider/model marked amber on the dropdown | Sep 2026 |
| Chat composer overhaul — Enter-to-send/Shift+Enter, taller input, per-message timestamps, "Conversation" relabeling | Sep 2026 |

## Rejected

| Suggestion | Why |
|---|---|
| Fork the ROI / investment agents back in | They moved to SONAR on purpose; two homes for the same logic is worse than one |
