"""
provision.py — Creating sites and the peers that connect to them.

All key material originates here, on your machine. The server receives derived
configuration; it never generates its own identity and never sees the CA key.
That inversion is the point of the whole design: a compromised VPS leaks the
traffic it is currently carrying, but it cannot mint new client certificates or
impersonate the site after you rebuild it.
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import keys, pki, store
from .model import MODE_NATIVE, MODE_REMOTE, Peer, Site, default_site


def init_site(
    name: str,
    mode: str,
    endpoint_host: str = "",
    *,
    enable_openvpn: bool = True,
    overwrite: bool = False,
) -> Site:
    """
    Create a new site and generate its full identity.

    This is the expensive, irreversible step: the WireGuard server keypair and
    the certificate authority are created once and everything else is derived
    from them.
    """
    if mode not in (MODE_NATIVE, MODE_REMOTE):
        raise ValueError(f"mode must be {MODE_NATIVE!r} or {MODE_REMOTE!r}, got {mode!r}")
    if store.site_exists(name) and not overwrite:
        raise FileExistsError(
            f"A site named {name!r} already exists. Loading it preserves the "
            "existing peers; overwriting invalidates every client config."
        )

    site = default_site(name, mode)
    site.endpoint_host = endpoint_host.strip()
    site.enable_openvpn = enable_openvpn

    private_key, public_key = keys.generate_wg_keypair()
    site.server_wg_private_key = private_key
    site.server_wg_public_key = public_key

    if enable_openvpn:
        _init_openvpn_pki(site)

    store.save_site(site)
    return site


def _init_openvpn_pki(site: Site) -> None:
    site.ca_cert_pem, site.ca_key_pem = pki.create_ca(site.name)
    site.server_cert_pem, site.server_key_pem = pki.issue_server_cert(
        site.ca_cert_pem,
        site.ca_key_pem,
        common_name=f"{site.name} server",
        endpoint_host=site.endpoint_host,
    )
    site.tls_crypt_key = keys.generate_tls_crypt_key()


def enable_openvpn(site: Site) -> Site:
    """Turn on the OpenVPN fallback for a site that was created without it."""
    if not site.ca_cert_pem:
        _init_openvpn_pki(site)
    site.enable_openvpn = True

    # Existing peers predate the PKI and have no certificate yet.
    for peer in site.peers:
        if not peer.has_openvpn:
            peer.ovpn_cert_pem, peer.ovpn_key_pem = pki.issue_client_cert(
                site.ca_cert_pem, site.ca_key_pem, common_name=peer.name
            )
    store.save_site(site)
    return site


def add_peer(site: Site, name: str, notes: str = "") -> Peer:
    """
    Add a client device to a site.

    Generates a WireGuard keypair, a per-peer pre-shared key, an address, and —
    if the fallback is enabled — an OpenVPN client certificate. The peer is
    saved immediately, because losing a generated private key means the config
    you just handed someone can never be reproduced.
    """
    name = name.strip()
    if not name:
        raise ValueError("Peer name cannot be empty.")
    if site.get_peer(name):
        raise ValueError(f"A peer named {name!r} already exists in this site.")

    address4, address6 = site.allocate_addresses()
    private_key, public_key = keys.generate_wg_keypair()

    peer = Peer(
        name=name,
        wg_private_key=private_key,
        wg_public_key=public_key,
        wg_preshared_key=keys.generate_preshared_key(),
        address4=address4,
        address6=address6,
        notes=notes,
    )

    if site.enable_openvpn and site.ca_cert_pem:
        peer.ovpn_cert_pem, peer.ovpn_key_pem = pki.issue_client_cert(
            site.ca_cert_pem, site.ca_key_pem, common_name=name
        )

    site.peers.append(peer)
    store.save_site(site)
    return peer


def remove_peer(site: Site, name: str) -> bool:
    """
    Remove a peer.

    The peer's address is freed for reuse. Note that revocation only takes
    effect once the server is redeployed — until then the removed device can
    still connect with the config it already holds.
    """
    peer = site.get_peer(name)
    if peer is None:
        return False
    site.peers.remove(peer)
    store.save_site(site)
    return True


def set_peer_enabled(site: Site, name: str, enabled: bool) -> bool:
    """
    Enable or disable a peer without discarding its keys.

    A disabled peer is left out of the server config on the next deploy but
    keeps its address and certificate, so it can be switched back on without
    reissuing anything to the device.
    """
    peer = site.get_peer(name)
    if peer is None:
        return False
    peer.enabled = enabled
    store.save_site(site)
    return True


def rotate_peer_keys(site: Site, name: str) -> Peer:
    """
    Replace a peer's key material, keeping its name and address.

    Use this when a device is lost. The old config stops working after the next
    deploy; the new one must be re-delivered to the device.
    """
    peer = site.get_peer(name)
    if peer is None:
        raise ValueError(f"No peer named {name!r}")

    peer.wg_private_key, peer.wg_public_key = keys.generate_wg_keypair()
    peer.wg_preshared_key = keys.generate_preshared_key()
    if site.enable_openvpn and site.ca_cert_pem:
        peer.ovpn_cert_pem, peer.ovpn_key_pem = pki.issue_client_cert(
            site.ca_cert_pem, site.ca_key_pem, common_name=peer.name
        )
    store.save_site(site)
    return peer


def rotate_server_keys(site: Site) -> Site:
    """
    Replace the server's WireGuard keypair.

    Every peer config embeds the server's public key, so all of them must be
    re-exported and re-delivered afterwards. The OpenVPN CA is left alone.
    """
    site.server_wg_private_key, site.server_wg_public_key = keys.generate_wg_keypair()
    store.save_site(site)
    return site


def set_endpoint(site: Site, host: str) -> Site:
    """
    Point the site at a new public address or hostname.

    Reissues the OpenVPN server certificate so its subject alternative names
    still cover the endpoint — otherwise clients verifying the server name
    would start failing.
    """
    site.endpoint_host = host.strip()
    if site.enable_openvpn and site.ca_cert_pem:
        site.server_cert_pem, site.server_key_pem = pki.issue_server_cert(
            site.ca_cert_pem,
            site.ca_key_pem,
            common_name=f"{site.name} server",
            endpoint_host=site.endpoint_host,
        )
    store.save_site(site)
    return site


def mark_deployed(site: Site) -> None:
    site.last_deployed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    store.save_site(site)
