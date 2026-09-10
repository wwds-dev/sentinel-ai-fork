# Tunnel — personal VPN design and troubleshooting

**Goal:** compare the current VPN state with an intended profile, understand the topology, and create a reviewable configuration or action plan. **Time:** 30 minutes.

![Tunnel workspace](docs/training/images/tunnel.png)

Tunnel is for infrastructure you own or administer. It has four distinct
paths: **Connection Check** reads current status, **Safe Action Preview** shows
but cannot run a proposed change, the **Advisor** uses an AI model, and **Build
Config** is deterministic and offline. A status check or preview does not send
anything to a model and does not count against an AI budget.

## Connection Check

Start here when a VPN is slow, appears disconnected, or you simply want to know
what this Mac can see. Choose a saved profile under **Compare profile**, leave
**Include public IP and latency** off, and select **Check Connection**. Choosing
a profile here does not activate it or change the VPN Agent's saved selection.
Tunnel then reports:

- whether the WireGuard app, `wg`, `wg-quick`, and OpenVPN command are present;
- active WireGuard interfaces and whether an OpenVPN process was detected;
- peer count, most recent WireGuard handshake, and transfer totals when the
  local `wg` status tool allows those reads;
- the current default network interface and gateway;
- the DNS servers configured on this Mac.
- whether the selected profile's interface is active, whether it has a recent
  handshake, whether its saved endpoint and port look usable, and whether the default
  route matches the interface.

The default check is entirely local and read-only. It does not ask for an admin
password, connect or disconnect a tunnel, alter a route, touch the firewall, or
read private keys.

### Optional external checks

Enable **Include public IP and latency** only when you need to compare the
visible internet address or basic reachability. Tunnel asks for confirmation
and names the destinations before it contacts them:

- `api.ipify.org` returns the public IP visible from the current connection;
- `1.1.1.1` is used for a latency test, with a TCP fallback when ping is blocked.

Declining the confirmation contacts neither destination. These results are
useful clues, not proof of anonymity or a complete leak test. A VPN interface
can be active while an application uses another route, and a configured DNS
server list does not show every resolver an application might contact.

### Reading the cards

1. Check **Connection summary** for the high-level state.
2. In **Detected tunnels**, a recent handshake is stronger evidence than an
   interface name alone. A zero or old handshake suggests that the interface
   exists but has not recently reached its peer.
3. Compare **Default interface** with the behavior you expect. Full-tunnel VPNs
   normally influence the default route; split tunnels may not.
4. Treat **Configured DNS servers** as context. If DNS behavior matters, follow
   up with the standalone VPN Agent's deeper checks.
5. Copy an individual card when asking the Advisor for help. Never copy private
   keys or complete secret configuration files into an AI request.

### Profile comparison

Tunnel reads the standalone VPN Agent's live profile list when it exists and
otherwise reads the bundled starter list. This read does not create a file,
save a selection, or expose key material. Select **No profile comparison** when
you only want a machine-wide snapshot.

Only non-secret profile fields enter Sentinel's report; key-like and unknown
fields are discarded. The comparison is intentionally cautious. An interface match plus a recent
handshake is strong evidence that the chosen WireGuard profile is communicating.
A present endpoint and valid port only mean the saved profile values look usable;
Tunnel deliberately does not query the live peer endpoint or claim that the
active interface is connected to that exact server.
A different default interface is not automatically a failure because split
tunnels legitimately keep the ordinary default route. For a full tunnel, a
route mismatch is a reason to inspect `AllowedIPs` and optionally compare the
public IP—not proof by itself.

On macOS, a tunnel managed by the WireGuard app may appear as an automatically
assigned `utun` interface instead of the profile's friendly name. Tunnel keeps
an exact-name mismatch visible and asks you to confirm it in the WireGuard app;
it does not assume that an arbitrary active `utun` belongs to the selected profile.

The **Recommended next steps** card prioritizes concrete follow-up work. Follow
only steps that fit your intended topology; it is guidance based on a snapshot,
not an automatic repair system.

## Safe Action Preview

Choose Connect, Disconnect, or Restart and select **Preview**. Tunnel shows:

- the exact profile and interface it would target;
- expected network effects, including possible route/DNS changes or a brief
  outage during restart;
- checks to perform before making the change manually;
- proposed `wg-quick` commands in a copyable card.

WireGuard is the only protocol currently supported by action previews. OpenVPN
and unknown protocols produce no command. The preview has no execution path. It does not open a shell, request an admin
password, or change a tunnel, route, DNS setting, or firewall rule. A missing or
unsafe interface name produces no command. After any manual change, return to
Connection Check and collect a fresh snapshot rather than relying on old status.

![Tunnel action preview](docs/training/images/tunnel-action-preview.png)

## Deployment choices

**Remote (VPS)** routes traffic through a rented server and can change the
public exit address. **Native (home LAN)** provides encrypted access back into
your home network; it normally does not hide or change your home public IP.

Choose WireGuard, OpenVPN TCP/443 fallback, or both. Enter the server host, SSH
user, home subnet and server egress interface where relevant. Incorrect routes
can cut off connectivity, so verify values before applying generated material.

## Advisor

Ask about topology, connection failures, firewalls, DNS/IPv6/WebRTC leaks or
kill-switch behaviour. Deployment fields are included as context. Review the
route before sending infrastructure details to a cloud model.

## Config Builder

Build Config produces server/client templates and a deployment runbook with
clearly marked key placeholders. It does not create real keys, connect to a
server or change system settings. Generate keys locally, protect private keys,
back up working configurations and keep an independent recovery session open
when changing a remote firewall.

## Beginner exercise

Run the local-only Connection Check with no VPN active. Identify which VPN
tools are installed and find the default interface. Explain why "no active
tunnel detected" is a status observation rather than proof of a fault.

## Intermediate exercise

Generate a Native WireGuard example for a fictional home subnet. Locate the
placeholders and explain why native mode does not change the internet exit IP.

Then select a saved profile and preview Disconnect. Identify the warning about
ordinary traffic resuming when no kill switch is active. Confirm that the VPN
remains unchanged after generating the preview.

## Independent exercise

With a VPN you own connected, run the local check twice: once immediately and
once after ordinary browsing. Compare handshake age and transfer totals. If you
also opt into the external check, record the public IP before and during the
tunnel without placing either address into an AI prompt. Write a short verdict
that separates observations, likely explanations, and what remains unverified.

## Best-practice checklist

- Keep an independent recovery session open before changing a remote firewall.
- Back up site state and client configurations before deployment or key rotation.
- Store private keys only in the VPN Agent's protected state location.
- Use the local check before the Advisor; send only the non-secret card needed
  to explain the problem.
- Treat an Action Preview as a review artifact. Confirm the target, keep recovery
  access available, and make the change through your normal trusted VPN tool.
- Treat an active tunnel, public-IP change, DNS configuration, and kill-switch
  behavior as separate checks. One passing result does not prove the others.
