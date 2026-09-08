# Tunnel — personal VPN design and troubleshooting

**Goal:** understand a VPN topology and create a reviewable configuration. **Time:** 20 minutes.

![Tunnel workspace](docs/training/images/tunnel.png)

Tunnel is for infrastructure you own or administer. It has two distinct paths:
the **Advisor** uses an AI model, while **Build Config** is deterministic,
offline and does not require a model.

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

## Exercise

Generate a Native WireGuard example for a fictional home subnet. Locate the
placeholders and explain why native mode does not change the internet exit IP.

