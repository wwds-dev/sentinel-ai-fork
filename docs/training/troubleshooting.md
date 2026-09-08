# Troubleshooting

**Goal:** resolve common problems without losing work. **Time:** as needed.

| Symptom | What it usually means | What to do |
|---|---|---|
| Provider is not enabled | Sentinel has no permission for that API | Review the route and enable the provider only if you intend to send the data |
| API key missing | No credential was detected | Add the correct key through the documented setup, restart, and check API readiness |
| Insufficient balance / HTTP 402 | The provider account cannot fund the request | Add provider credit or deliberately choose another route; never assume Auto-route changes providers silently |
| Budget exceeded | A Sentinel cap blocked the request | Review Cost history, then change the cap only if the spend is intended |
| Ollama unavailable | The local service is stopped or the model is absent | Start Ollama, install/select an available model, then refresh models |
| App feels slow | A local model or scan is using resources | Check Inspector, wait, stop the task or select a smaller model |
| No live research result | Source failed, rate-limited or had no match | Read Trace Activity; keep successful partial results and retry only when appropriate |
| File discovery permission error | The current local/SSH account cannot read a folder | Choose an accessible folder or correct account permissions outside Sentinel |
| Unknown SSH host key | The machine is not trusted in `known_hosts` | Verify the fingerprint independently before adding it with normal SSH tools |
| Stop appears ineffective | A provider/process may already be finishing | Wait briefly and check Run log; cancellation cannot recall data already sent |
| Portable volume unavailable/read-only/low-space | The USB drive was ejected, mounted without write access, or has under 256 MiB free | Stop, reconnect or repair the volume, free space, then restart; Sentinel will not redirect portable data elsewhere |

## Preserve evidence

Before retrying, save useful partial output, copy the exact error, record the
agent, route and time, and inspect Run log. Do not repeatedly send a failing
paid request. Restart the app after interface updates because an already-running
process cannot load changed Python code.

## Escalation information

When asking for help, provide the visible error, reproduction steps, selected
agent/provider/model, whether the task works locally, and the relevant Run log
entry. Remove API keys, passwords and private target information first.
