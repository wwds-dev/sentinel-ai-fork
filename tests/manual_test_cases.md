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
- [ ] The Activity trail remains visible after completion and accurately states that Structure Query contacted no external sources.
- [ ] A completed run appears under Saved Searches and can be reopened without issuing another model or network request.
- [ ] Auto-detect records the resolved target type; malformed typed email, domain, phone, username, or IP input is blocked before authorization.
- [ ] Live Research for a domain names WHOIS, DNS, and crt.sh before confirmation and contacts nothing when confirmation is declined.
- [ ] The Activity trail records each source actually contacted, retains successful results if another source fails, and saves the collected record under Saved Searches.
- [ ] Stopping Live Research preserves completed source results and marks the run as partial/cancelled.
- [ ] Username Live Research names URLScan before confirmation and records only URLScan as contacted.
- [ ] Email Live Research sends the address only to checked services; HIBP and BreachDirectory start off, and HIBP is unavailable without a key.
- [ ] Company Live Research names GLEIF before confirmation, shows the LEI coverage limitation, and saves legal-entity results in Saved Searches.
- [ ] Person and Phone Live Research contacts nothing and explains that Trace does not use people-search, reverse-phone, or data-broker services.
- [ ] A skipped email service is recorded as skipped-before-contact rather than contacted or failed.

## 4. Bloodhound (`osint_heavy`)

1. Select **Bloodhound** and use a lawful, non-sensitive test target.
2. Configure a small investigation and start collection.

- [ ] The panel shows collection progress and provider results.
- [ ] Failed or unavailable providers are reported without discarding successful results.
- [ ] The final dossier distinguishes collected evidence, inference, and unknowns.
- [ ] The report includes lawful-use/privacy guidance and is logged under `osint_heavy`.
- [ ] Stop cancels active work cleanly.

3. Expand **Local File Discovery**, add a small test folder, and search by a
   partial name, extension, size, and modified date.

- [ ] Bloodhound searches only folders explicitly listed by the user.
- [ ] Results show name, path, type, size, and modified time and can be sorted.
- [ ] Cancel stops a large search without freezing the interface.
- [ ] Inaccessible folders produce a clear warning while readable folders continue.
- [ ] Reaching the safety limit asks the user to narrow the search.
- [ ] Double-clicking a result reveals its containing folder and changes no files.

4. Select **Remote SSH machine** and enter an owned test host already present in
   `known_hosts`, an SSH-agent-backed user, and a small absolute remote folder.

- [ ] Unknown or changed host keys are rejected instead of silently trusted.
- [ ] The search uses SFTP and returns the same metadata columns and filters.
- [ ] Authentication and offline errors are clear and do not expose credentials.
- [ ] Open SSH Terminal hands the destination to the system SSH application.

## 5. Beacon (`wifi`)

1. Select **Beacon** on a machine with no external Wi-Fi adapter attached.
2. Run Connection Preflight and adapter detection, then request diagnostic guidance for an owned test network.

- [ ] Adapter state is reported accurately and absence does not crash the panel.
- [ ] Guidance separates local macOS diagnostics from Kali/aircrack-ng commands.
- [ ] Preflight labels the default route as internet/control and performs no mode or connection changes.
- [ ] With no separate routed interface, Kali planning visibly warns that monitor mode could remove internet access.
- [ ] VM guidance explains USB passthrough detachment and guest-driver limitations.
- [ ] Offensive commands include an explicit authorisation warning.
- [ ] Generated commands identify placeholders and are not executed automatically.
- [ ] The request is logged under `wifi`.

### Portable USB acceptance

1. Build to a writable test volume with `scripts/build_portable.sh`.
2. Add fictional settings/history to `Sentinel Fork Data`, rebuild to the same destination, and launch again.

- [ ] The app, marker, launcher and explicit data folder are present.
- [ ] Existing data survives the upgrade and the source `.env` was not copied.
- [ ] No portable run creates state in Application Support or the Lab checkout.
- [ ] Read-only, unavailable and under-256-MiB volumes produce clear errors.
- [ ] Quitting followed by Finder eject leaves the volume cleanly removable.
- [ ] Emergency Reset is hidden in normal/dev mode and visible only in portable mode.
- [ ] A wrong confirmation phrase or second-stage cancellation changes nothing.
- [ ] A confirmed reset removes the portable database, histories, logs, settings and `.env`, preserves unrelated USB files, quits, and does not recreate window preferences.

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

1. Select **Tunnel** with no VPN active and run **Check Connection** while
   **Include public IP and latency** is off.

- [ ] The result has structured cards for summary, installed tools, detected tunnels, local route/DNS, and interpretation.
- [ ] No provider permission or model-cost confirmation appears.
- [ ] The check does not request an administrator password or change network state.
- [ ] Missing `wg`, `wg-quick`, OpenVPN, or route access is reported without crashing.
- [ ] Stop requests cancellation and leaves the panel usable.

2. Select a saved profile and run the local check again.

- [ ] The active VPN Agent profile is preselected when it exists; choosing it in Sentinel does not modify the profile file.
- [ ] The comparison card shows the profile name, interface, endpoint and port without displaying keys.
- [ ] Matching interfaces, handshakes and routes are described as ready; mismatches produce plain-language next steps.
- [ ] Endpoint/port findings state that saved values are present but the live peer endpoint is not verified.
- [ ] A different default interface is described as potentially normal for a split tunnel rather than an automatic failure.
- [ ] Closing Sentinel or committing Portable Emergency Reset during a check cancels and joins the Tunnel worker before the app exits or erases data.

3. Enable **Include public IP and latency**, decline its confirmation, and run again.

- [ ] The confirmation names `api.ipify.org` and `1.1.1.1`.
- [ ] Declining starts no worker and contacts no external destination.

4. On a VPN you own, accept the optional check and compare results before and
   after connecting.

- [ ] WireGuard status shows peer count, handshake age, and aggregate transfer totals without displaying key material.
- [ ] Results clearly state that an active interface or configured DNS list is not proof that all traffic is protected.

5. Preview Connect, Disconnect and Restart for the selected profile.

- [ ] Each preview names the selected profile and interface, expected effects, checks and proposed commands.
- [ ] Previewing requests no provider authorization, admin password, subprocess, or network-state change.
- [ ] A missing or unsafe interface produces no command.
- [ ] Disconnect warns that ordinary traffic may resume when no kill switch is active.

6. Test both remote VPS and owned-LAN/native modes with placeholder values.
7. Generate a plan or configuration without deploying it.

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
