"""
export.py — Getting a config onto a device.

Three delivery routes, because devices differ:

  .conf / .ovpn files  Desktop clients import these directly.
  QR code              Phones scan it in the WireGuard app. Only WireGuard —
                       an .ovpn carries an inlined certificate chain and blows
                       past what a QR code can hold.
  profile registration Adds the site to config/vpn_profiles.json so the rest of
                       VPN Agent can monitor the tunnel it just created.

Exported files land outside the repo with owner-only permissions. They contain
private keys; treat one like a password, and delete it once the device has
imported it.
"""

from __future__ import annotations

import json
from pathlib import Path

import segno

from . import obfuscation, paths, render
from .model import OBFS_STUNNEL, Peer, Site

QR_SCALE = 6
QR_BORDER = 2

# A WireGuard config is ~400 bytes and fits comfortably; this guards against a
# pathological site with a huge lan_routes list producing an unscannable code.
QR_MAX_BYTES = 2000


def export_peer(
    site: Site,
    peer: Peer,
    *,
    directory: Path | None = None,
    include_openvpn: bool = True,
    include_qr: bool = True,
) -> dict[str, Path]:
    """
    Write every config format for one peer.

    Returns a mapping of format name to path.
    """
    target = directory or paths.exports_dir(site.name)
    paths.ensure_private_dir(target)

    slug = paths.slugify(peer.name)
    written: dict[str, Path] = {}

    wg_text = render.wg_client_config(site, peer)
    written["wireguard"] = paths.write_private(target / f"{slug}.conf", wg_text)

    if include_qr:
        qr_path = _write_qr(wg_text, target / f"{slug}-qr.png")
        if qr_path is not None:
            written["qr"] = qr_path

    if include_openvpn and site.enable_openvpn and peer.has_openvpn:
        ovpn_text = render.ovpn_client_config(site, peer)
        written["openvpn"] = paths.write_private(target / f"{slug}.ovpn", ovpn_text)

        # A stunnel-fronted server needs three files on the device, not one:
        # the profile, the stunnel config it connects through, and the CA that
        # lets stunnel verify the server rather than trusting anything.
        if site.obfuscation == OBFS_STUNNEL:
            written["stunnel"] = paths.write_private(
                target / "stunnel-client.conf", obfuscation.stunnel_client_config(site)
            )
            written["ca"] = paths.write_private(target / "ca.crt", site.ca_cert_pem)

    notes = obfuscation.client_instructions(site)
    if notes:
        written["readme"] = paths.write_private(target / "READ-ME-FIRST.txt", notes)

    return written


def export_all_peers(site: Site, *, directory: Path | None = None) -> dict[str, dict[str, Path]]:
    """Export configs for every peer in a site."""
    return {peer.name: export_peer(site, peer, directory=directory) for peer in site.peers}


def _write_qr(text: str, path: Path) -> Path | None:
    if len(text.encode("utf-8")) > QR_MAX_BYTES:
        return None
    paths.ensure_private_dir(path.parent)
    qr = segno.make(text, error="m")
    qr.save(str(path), scale=QR_SCALE, border=QR_BORDER, kind="png")
    path.chmod(paths.FILE_MODE)
    return path


def qr_terminal(site: Site, peer: Peer) -> str:
    """Render the peer's WireGuard config as a QR code drawn in text."""
    import io

    text = render.wg_client_config(site, peer)
    if len(text.encode("utf-8")) > QR_MAX_BYTES:
        return "(config too large for a QR code — use the .conf file)"
    buffer = io.StringIO()
    segno.make(text, error="m").terminal(out=buffer, border=QR_BORDER)
    return buffer.getvalue()


# ── Registering with the client side ─────────────


def register_profile(
    site: Site,
    profiles_path: Path | None = None,
    *,
    interface: str | None = None,
) -> bool:
    """
    Add (or update) this site in the client-side profile list.

    That list is what the main window's dropdown, the latency test and the
    health monitor all read, so registering here is what makes a server you
    just built visible to the monitoring half of the app.

    Returns True if the file was modified.
    """
    path = profiles_path or _default_profiles_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        data = {"profiles": [], "active_profile": ""}

    profiles = data.setdefault("profiles", [])
    entry = {
        "name": site.name,
        "endpoint": site.endpoint_host,
        "port": site.wg_port,
        "interface": interface or _client_interface(site),
        "notes": f"Built by VPN Agent ({site.mode} mode, {len(site.peers)} peer(s))",
    }

    for index, existing in enumerate(profiles):
        if existing.get("name") == site.name:
            if existing == entry:
                return False
            profiles[index] = entry
            break
    else:
        profiles.append(entry)

    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=4)
    return True


def _client_interface(site: Site) -> str:
    """
    The interface name the *client* will use.

    Deliberately not the server's interface name: on macOS wg-quick names the
    interface after the .conf file, and a client importing "<site>.conf" gets an
    interface called after the site, not after the server's wg0.
    """
    return paths.slugify(site.name)


def _default_profiles_path() -> Path:
    """
    The same writable profile list the Monitor tab reads.

    Deliberately not the config/ copy — that one is a read-only seed that ends
    up inside the .app bundle once frozen.
    """
    path = paths.profiles_file()
    paths.ensure_private_dir(path.parent)
    return path


# ── Human-readable summary ───────────────────────


def site_summary(site: Site) -> str:
    """A short plain-text report on a site — used by the CLI and the GUI."""
    from . import pki

    lines = [
        f"Site:        {site.name}",
        f"Mode:        {site.mode}",
        f"Endpoint:    {site.endpoint_host or '(not set)'}",
        f"WireGuard:   UDP {site.wg_port}  interface {site.wg_interface}",
    ]
    if site.enable_openvpn:
        lines.append(f"OpenVPN:     TCP {site.ovpn_port} (fallback)")
    else:
        lines.append("OpenVPN:     disabled")

    lines += [
        f"Tunnel:      {'full (all traffic)' if site.full_tunnel else 'split'}",
        f"Client routes: {site.client_allowed_ips()}",
        f"DNS pushed:  {', '.join(site.dns) if site.dns else '(none)'}",
        f"Subnet:      {site.wg_subnet4}"
        + (f" / {site.wg_subnet6}" if site.enable_ipv6 else ""),
        f"Deployed:    {site.last_deployed_at or 'never'}",
        "",
        f"Peers ({len(site.peers)}):",
    ]

    if not site.peers:
        lines.append("  (none — add one before deploying)")
    for peer in site.peers:
        state = "" if peer.enabled else "  [disabled]"
        ovpn = " +ovpn" if peer.has_openvpn else ""
        lines.append(f"  {peer.name:<20} {peer.ip4:<15}{ovpn}{state}")

    if site.enable_openvpn and site.ca_cert_pem:
        info = pki.describe_cert(site.ca_cert_pem)
        lines += ["", f"CA expires:  {info['not_after']} ({info['days_remaining']} days)"]

    return "\n".join(lines)
