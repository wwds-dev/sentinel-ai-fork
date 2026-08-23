# Sentinel Fork — Manual Acceptance Checklist

Use a disposable test database and non-sensitive prompts. Do not send paid requests unless the matching provider permission is enabled and the cost confirmation is understood. Security tests must use systems and networks you own or are explicitly authorised to assess.

## 1. Built-in roster and navigation

- [ ] The sidebar shows exactly: Chat, Trace, Bloodhound, Beacon, Bug Spray, Tunnel, Forge.
- [ ] Each button opens the matching workspace and highlights the selected agent.
- [ ] Writing, Coding, Router, Narrator, and moved/deleted product agents do not appear as sidebar agents.
- [ ] The saved-chat filter offers the seven built-ins plus the all-agents option.
- [ ] Switching agents does not display another panel's controls.

## 2. Chat

### General conversation

1. Select **Chat** and **General Chat**.
2. Use a local model and ask: `Explain the difference between hashing and encryption in plain language.`

- [ ] A relevant response streams into the output area.
- [ ] Stop cancels an in-progress response without freezing the app.
- [ ] The completed request appears in run history and saved chats.
- [ ] Usage and cost indicators update appropriately for the selected provider.

### Writing tool

1. Keep **Chat** selected and choose **Writing** from the Tool selector.
2. Submit: `Rewrite this clearly and professionally: We fixed the thing and it should be okay now.`

- [ ] The response improves clarity and tone without inventing facts.
- [ ] The run is recorded under Chat with Writing as the tool.
- [ ] No standalone Writing agent is selected or created.

### Coding tool

1. Keep **Chat** selected and choose **Coding**.
2. Submit: `Explain the bug and provide a corrected version: def first(items): return items[1]`

- [ ] The response identifies the indexing issue and discusses empty-input handling.
- [ ] The run is recorded under Chat with Coding as the tool.
- [ ] No standalone Coding agent is selected or created.

## 3. Trace (`osint`)

1. Select **Trace**.
2. Enter a domain you own or a reserved example domain and choose an appropriate query type.
3. Run the analysis with an allowed provider.

- [ ] Empty or invalid targets are rejected before a paid request.
- [ ] The response provides a focused research plan, useful source types, and clear next steps.
- [ ] Claims are framed as leads to verify rather than unsupported facts.
- [ ] The request is logged under `osint` and can be stopped safely.

## 4. Bloodhound (`osint_heavy`)

1. Select **Bloodhound** and use a lawful, non-sensitive test target.
2. Configure a small investigation and start collection.

- [ ] The panel shows collection progress and provider results.
- [ ] Failed or unavailable providers are reported without discarding successful results.
- [ ] The final dossier distinguishes collected evidence, inference, and unknowns.
- [ ] The report includes lawful-use/privacy guidance and is logged under `osint_heavy`.
- [ ] Stop cancels active work cleanly.

## 5. Beacon (`wifi`)

1. Select **Beacon** on a machine with no external Wi-Fi adapter attached.
2. Run adapter detection and request diagnostic guidance for an owned test network.

- [ ] Adapter state is reported accurately and absence does not crash the panel.
- [ ] Guidance separates local macOS diagnostics from Kali/aircrack-ng commands.
- [ ] Offensive commands include an explicit authorisation warning.
- [ ] Generated commands identify placeholders and are not executed automatically.
- [ ] The request is logged under `wifi`.

## 6. Bug Spray (`bug_bounty`)

1. Select **Bug Spray**.
2. Provide a fictional or explicitly in-scope program, target, and harmless sample finding.
3. Generate triage or report output.

- [ ] Missing scope/target information blocks or warns before analysis.
- [ ] The response distinguishes evidence from assumptions and does not claim unperformed exploitation.
- [ ] The report includes reproducible steps, impact, evidence placeholders, and remediation.
- [ ] The workflow keeps the authorised-program boundary visible.
- [ ] The request is logged under `bug_bounty` and Stop works.

## 7. Tunnel (`vpn`)

1. Select **Tunnel** and test both remote VPS and owned-LAN/native modes with placeholder values.
2. Generate a plan or configuration without deploying it.

- [ ] Remote and native modes explain their different traffic and exit-IP behaviour.
- [ ] Native mode defaults to appropriate split-tunnel guidance unless explicitly changed.
- [ ] Output marks keys, addresses, interfaces, and hostnames that require replacement.
- [ ] Kill-switch, firewall, DNS, and rollback considerations are included where relevant.
- [ ] Nothing is deployed or executed automatically.
- [ ] The request is logged under `vpn` and Stop works.

## 8. Forge (`manager`)

1. Select **Forge** and describe a harmless agent that summarizes local text supplied by the user.
2. Analyze the idea, inspect the generated specification, then cancel before approval.

- [ ] Forge produces a structured, reviewable specification.
- [ ] Cancelling does not create files or registry records.

Repeat with a disposable agent name and approve the reviewed specification.

- [ ] The generated key is valid and does not collide with a built-in key.
- [ ] Approval creates only the expected agent definition and dynamic registry entries.
- [ ] The UI clearly says the result is an inactive scaffold and is not added to the sidebar automatically.
- [ ] Generated code is not silently granted providers, tools, or external access beyond the approved spec.
- [ ] The request is logged under `manager`.

## 9. Shared permissions, budgets, and persistence

- [ ] A disabled cloud-provider permission blocks the request before network use.
- [ ] Local Ollama requests do not require a cloud permission.
- [ ] Session and daily budget limits block requests that would exceed them.
- [ ] Cancelling or failing a request closes its run with the correct status.
- [ ] Restarting the app preserves settings, saved chats, usage, and run history.
- [ ] Historical records for retired agent keys remain readable without adding those keys to the active roster.
- [ ] Settings and registry views agree with the seven built-in agents; dynamic Forge agents are clearly separate.
