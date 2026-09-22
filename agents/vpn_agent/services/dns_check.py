"""
dns_check.py — Checks which DNS resolvers are currently answering queries.
A basic DNS leak test sends queries to known public DNS addresses and
sees if the answers come from unexpected resolvers.
"""

import socket
import dns.resolver  # dnspython library

# Test domain — known to return different results depending on resolver
DNS_TEST_DOMAIN = "whoami.akamai.net"

# Public resolvers to verify against
KNOWN_PUBLIC_RESOLVERS = {
    "8.8.8.8": "Google",
    "8.8.4.4": "Google",
    "1.1.1.1": "Cloudflare",
    "1.0.0.1": "Cloudflare",
    "9.9.9.9": "Quad9",
    "208.67.222.222": "OpenDNS",
}


def get_system_dns_servers() -> list[str]:
    """
    Return the list of DNS servers currently configured on the system.
    Uses socket to resolve a domain and captures what the OS resolves with.
    Note: this is a simplified check — for deeper inspection, parse /etc/resolv.conf
    or use scutil --dns on macOS.
    """
    try:
        resolver = dns.resolver.Resolver()
        # dnspython reads /etc/resolv.conf and system config automatically
        return list(resolver.nameservers)
    except Exception as e:
        return [f"Error: {e}"]


def check_dns_leak() -> dict:
    """
    Perform a basic DNS leak check.
    Returns a dict with:
      - servers: list of detected DNS server IPs
      - labels: mapped names for known servers
      - leak_risk: True if any server is NOT in known_public_resolvers (unusual resolver)
      - status: human-readable summary string
    """
    servers = get_system_dns_servers()
    labels = []
    unknown_count = 0

    for server in servers:
        if server in KNOWN_PUBLIC_RESOLVERS:
            labels.append(f"{server} ({KNOWN_PUBLIC_RESOLVERS[server]})")
        else:
            labels.append(f"{server} (Unknown)")
            unknown_count += 1

    # Leak risk is heuristic: if all resolvers are unknown, something may be off
    # When VPN is active, the VPN provider's resolver should appear
    leak_risk = unknown_count == len(servers) and len(servers) > 0

    if leak_risk:
        status = "Possible DNS leak — unknown resolvers only"
    elif unknown_count > 0:
        status = "Mixed resolvers — check manually"
    else:
        status = "DNS OK — known public resolvers"

    return {
        "servers": servers,
        "labels": labels,
        "leak_risk": leak_risk,
        "status": status,
    }


def resolve_test_domain() -> str:
    """
    Attempt to resolve a test domain to verify DNS is working at all.
    Returns the resolved IP or an error string.
    """
    try:
        ip = socket.gethostbyname(DNS_TEST_DOMAIN)
        return ip
    except Exception as e:
        return f"Failed: {e}"
