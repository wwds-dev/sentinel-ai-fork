"""
model.py — The objects a VPN deployment is made of.

A Site is one VPN server you own. It holds every piece of long-lived state:
the server's WireGuard keys, the OpenVPN certificate authority, the address
plan, and the list of peers. Peers hold their own key material so a config can
be re-exported later without regenerating (and thus invalidating) the peer.

Two deployment modes, which differ in exactly one interesting way — where the
traffic comes out:

  native  The server runs on hardware you own on your own LAN (a Raspberry Pi,
          a spare Linux box, this Mac). Traffic exits through your home ISP, so
          this buys you an encrypted way *into* your network from outside, not
          a different apparent location. Defaults to a split tunnel.

  remote  The server runs on a rented host reachable over SSH. Traffic exits
          there, so your apparent IP becomes the server's. Defaults to a full
          tunnel.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

MODE_NATIVE = "native"
MODE_REMOTE = "remote"
MODES = (MODE_NATIVE, MODE_REMOTE)

DEFAULT_WG_PORT = 51820
DEFAULT_OVPN_PORT = 443
DEFAULT_WG_SUBNET4 = "10.66.66.0/24"
DEFAULT_WG_SUBNET6 = "fd42:66:66::/64"
DEFAULT_OVPN_SUBNET4 = "10.67.67.0/24"
DEFAULT_DNS = ("1.1.1.1", "1.0.0.1")

# Obfuscation options for the OpenVPN fallback.
OBFS_NONE = "none"
OBFS_STUNNEL = "stunnel"
OBFS_MODES = (OBFS_NONE, OBFS_STUNNEL)

# Where OpenVPN listens when stunnel is fronting it. Loopback only — the whole
# point is that nothing but stunnel can reach it.
DEFAULT_OVPN_LOCAL_PORT = 1194

# Addresses .1 is the server; peers start here.
FIRST_PEER_OFFSET = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Peer:
    """One client device: a phone, a laptop, a router."""

    name: str
    wg_private_key: str
    wg_public_key: str
    wg_preshared_key: str
    address4: str                       # e.g. "10.66.66.2/32"
    address6: str = ""                  # e.g. "fd42:66:66::2/128"
    ovpn_cert_pem: str = ""
    ovpn_key_pem: str = ""
    enabled: bool = True
    created_at: str = field(default_factory=_utc_now)
    notes: str = ""

    @property
    def ip4(self) -> str:
        """The bare v4 address without the prefix length."""
        return self.address4.split("/")[0]

    @property
    def has_openvpn(self) -> bool:
        return bool(self.ovpn_cert_pem and self.ovpn_key_pem)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Peer":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class SSHTarget:
    """How to reach a remote host. Never holds a password — keys only."""

    host: str = ""
    user: str = "root"
    port: int = 22
    identity_file: str = ""             # path to a private key; empty = ssh default

    def is_configured(self) -> bool:
        return bool(self.host)

    def destination(self) -> str:
        return f"{self.user}@{self.host}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SSHTarget":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Site:
    """A complete VPN server deployment."""

    name: str
    mode: str = MODE_REMOTE

    # How clients reach the server. For native mode this is usually a dynamic
    # DNS name, because a home IP moves.
    endpoint_host: str = ""
    wg_port: int = DEFAULT_WG_PORT
    ovpn_port: int = DEFAULT_OVPN_PORT
    enable_openvpn: bool = True

    # Concealment. `stunnel` fronts OpenVPN with a real TLS listener, so what a
    # deep-packet inspector sees on the wire is an ordinary HTTPS handshake
    # rather than OpenVPN's own. An onion service makes the server reachable
    # without any public address at all, which is the only option behind CGNAT.
    obfuscation: str = OBFS_NONE
    ovpn_local_port: int = DEFAULT_OVPN_LOCAL_PORT
    onion_enabled: bool = False
    onion_address: str = ""          # learned from the server after a deploy

    # Address plan
    wg_subnet4: str = DEFAULT_WG_SUBNET4
    wg_subnet6: str = DEFAULT_WG_SUBNET6
    ovpn_subnet4: str = DEFAULT_OVPN_SUBNET4
    enable_ipv6: bool = True

    # Routing
    full_tunnel: bool = True
    lan_routes: list[str] = field(default_factory=list)
    dns: list[str] = field(default_factory=lambda: list(DEFAULT_DNS))

    # Server identity
    wg_interface: str = "wg0"
    server_wg_private_key: str = ""
    server_wg_public_key: str = ""

    # OpenVPN PKI
    ca_cert_pem: str = ""
    ca_key_pem: str = ""
    server_cert_pem: str = ""
    server_key_pem: str = ""
    tls_crypt_key: str = ""

    ssh: SSHTarget = field(default_factory=SSHTarget)
    peers: list[Peer] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now)
    last_deployed_at: str = ""

    # ── Derived addressing ────────────────────────

    @property
    def server_ip4(self) -> str:
        """First usable address in the WireGuard subnet."""
        net = ipaddress.ip_network(self.wg_subnet4, strict=False)
        return str(net.network_address + 1)

    @property
    def server_ip6(self) -> str:
        net = ipaddress.ip_network(self.wg_subnet6, strict=False)
        return str(net.network_address + 1)

    @property
    def wg_prefix4(self) -> int:
        return ipaddress.ip_network(self.wg_subnet4, strict=False).prefixlen

    @property
    def server_address4(self) -> str:
        return f"{self.server_ip4}/{self.wg_prefix4}"

    @property
    def server_address6(self) -> str:
        prefix = ipaddress.ip_network(self.wg_subnet6, strict=False).prefixlen
        return f"{self.server_ip6}/{prefix}"

    def allocate_addresses(self) -> tuple[str, str]:
        """
        Pick the lowest free address for a new peer.

        Reuses gaps left by removed peers, so a site that churns devices does
        not march off the end of a /24.
        """
        net4 = ipaddress.ip_network(self.wg_subnet4, strict=False)
        taken = {p.ip4 for p in self.peers}

        chosen4 = None
        for offset in range(FIRST_PEER_OFFSET, net4.num_addresses - 1):
            candidate = str(net4.network_address + offset)
            if candidate not in taken:
                chosen4 = candidate
                break
        if chosen4 is None:
            raise ValueError(
                f"No free addresses left in {self.wg_subnet4} "
                f"({len(self.peers)} peers already allocated)"
            )

        address4 = f"{chosen4}/32"
        address6 = ""
        if self.enable_ipv6:
            net6 = ipaddress.ip_network(self.wg_subnet6, strict=False)
            host_offset = int(ipaddress.ip_address(chosen4)) - int(net4.network_address)
            address6 = f"{net6.network_address + host_offset}/128"
        return address4, address6

    # ── Routing policy ────────────────────────────

    def client_allowed_ips(self) -> str:
        """
        The AllowedIPs a client puts in its config — i.e. what it routes into
        the tunnel.

        Full tunnel sends everything. Split tunnel sends only the VPN subnet
        plus whatever LAN ranges you named, which is the sane default when the
        server sits on your own network and its exit IP is your own ISP anyway.
        """
        if self.full_tunnel:
            return "0.0.0.0/0, ::/0" if self.enable_ipv6 else "0.0.0.0/0"

        routes = [self.wg_subnet4]
        if self.enable_ipv6:
            routes.append(self.wg_subnet6)
        routes.extend(r for r in self.lan_routes if r)
        return ", ".join(routes)

    def server_allowed_ips(self, peer: Peer) -> str:
        """
        The AllowedIPs the *server* lists for a peer.

        This is a routing table entry and an access-control rule at once: only
        packets with these source addresses are accepted from this peer. It is
        always just that peer's own address — never a wildcard.
        """
        parts = [peer.address4]
        if self.enable_ipv6 and peer.address6:
            parts.append(peer.address6)
        return ", ".join(parts)

    @property
    def ovpn_bind_port(self) -> int:
        """
        The port the OpenVPN daemon listens on.

        With stunnel in front it retreats to a loopback port and stunnel takes
        the public one; otherwise it holds the public port itself.
        """
        return self.ovpn_local_port if self.obfuscation == OBFS_STUNNEL else self.ovpn_port

    @property
    def ovpn_binds_loopback_only(self) -> bool:
        return self.obfuscation == OBFS_STUNNEL

    def natted_subnets(self) -> list[str]:
        """Subnets the server must masquerade for outbound traffic."""
        subnets = [self.wg_subnet4]
        if self.enable_openvpn:
            subnets.append(self.ovpn_subnet4)
        return subnets

    # ── Peer management ───────────────────────────

    def get_peer(self, name: str) -> Peer | None:
        for peer in self.peers:
            if peer.name == name:
                return peer
        return None

    def peer_names(self) -> list[str]:
        return [p.name for p in self.peers]

    # ── Validation ────────────────────────────────

    def validate(self) -> list[str]:
        """Return a list of problems that would break a deployment."""
        problems: list[str] = []

        if not self.name.strip():
            problems.append("Site name is empty.")
        if self.mode not in MODES:
            problems.append(f"Unknown mode {self.mode!r} (expected one of {MODES}).")
        if not self.endpoint_host.strip():
            problems.append(
                "No endpoint host set — clients need a public IP or DNS name to connect to."
            )
        if not (1 <= self.wg_port <= 65535):
            problems.append(f"WireGuard port {self.wg_port} is out of range.")
        if self.enable_openvpn and not (1 <= self.ovpn_port <= 65535):
            problems.append(f"OpenVPN port {self.ovpn_port} is out of range.")
        if self.enable_openvpn and self.ovpn_port == self.wg_port:
            problems.append(
                "WireGuard and OpenVPN are on the same port number. They use "
                "different transports (UDP vs TCP) so this can work, but it is "
                "confusing — pick separate ports."
            )
        if not self.server_wg_private_key:
            problems.append("Server has no WireGuard key — the site was never initialised.")
        if self.enable_openvpn and not self.ca_cert_pem:
            problems.append("OpenVPN is enabled but the site has no certificate authority.")

        for label, subnet in (
            ("wg_subnet4", self.wg_subnet4),
            ("ovpn_subnet4", self.ovpn_subnet4),
        ):
            try:
                net = ipaddress.ip_network(subnet, strict=False)
            except ValueError as exc:
                problems.append(f"{label}: {exc}")
                continue
            if not net.is_private:
                problems.append(
                    f"{label} ({subnet}) is not a private range — this will collide "
                    "with real internet addresses."
                )

        try:
            wg4 = ipaddress.ip_network(self.wg_subnet4, strict=False)
            ovpn4 = ipaddress.ip_network(self.ovpn_subnet4, strict=False)
            if self.enable_openvpn and wg4.overlaps(ovpn4):
                problems.append(
                    f"WireGuard subnet {self.wg_subnet4} overlaps the OpenVPN subnet "
                    f"{self.ovpn_subnet4}; the two would fight over routes."
                )
        except ValueError:
            pass  # already reported above

        if self.obfuscation not in OBFS_MODES:
            problems.append(
                f"Unknown obfuscation {self.obfuscation!r} (expected one of {OBFS_MODES})."
            )
        if self.obfuscation == OBFS_STUNNEL and not self.enable_openvpn:
            problems.append(
                "stunnel obfuscation wraps the OpenVPN fallback, but OpenVPN is "
                "disabled — there would be nothing behind it."
            )
        if self.obfuscation == OBFS_STUNNEL and self.ovpn_local_port == self.ovpn_port:
            problems.append(
                "With stunnel in front, OpenVPN must listen on a different (loopback) "
                "port than the public one stunnel occupies."
            )
        if self.onion_enabled and not self.enable_openvpn:
            problems.append(
                "An onion service can only carry TCP, so it fronts the OpenVPN "
                "fallback — which is disabled."
            )

        if self.mode == MODE_REMOTE and not self.ssh.is_configured():
            problems.append("Remote mode needs an SSH host to deploy to.")

        seen: set[str] = set()
        for peer in self.peers:
            if peer.name in seen:
                problems.append(f"Duplicate peer name: {peer.name}")
            seen.add(peer.name)

        return problems

    # ── Serialisation ─────────────────────────────

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ssh"] = self.ssh.to_dict()
        data["peers"] = [p.to_dict() for p in self.peers]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Site":
        data = dict(data)
        ssh = SSHTarget.from_dict(data.pop("ssh", {}) or {})
        peers = [Peer.from_dict(p) for p in data.pop("peers", []) or []]
        known = {f for f in cls.__dataclass_fields__}
        site = cls(**{k: v for k, v in data.items() if k in known})
        site.ssh = ssh
        site.peers = peers
        return site


def default_site(name: str, mode: str) -> Site:
    """
    Build an unprovisioned Site with defaults that suit the chosen mode.

    Crypto material is not generated here — see provision.init_site.
    """
    site = Site(name=name, mode=mode)
    if mode == MODE_NATIVE:
        # A server on your own LAN exits through your own ISP, so forcing all
        # traffic through it gains nothing and costs you a hop. Route only the
        # VPN subnet and your LAN by default.
        site.full_tunnel = False
        site.lan_routes = ["192.168.1.0/24"]
    else:
        site.full_tunnel = True
    return site
