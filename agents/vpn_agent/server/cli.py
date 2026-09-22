"""
cli.py — Command-line access to the server toolkit.

    python -m server.cli init "Berlin VPS" --mode remote --host 1.2.3.4 --ssh root@1.2.3.4
    python -m server.cli peer add "Berlin VPS" iphone
    python -m server.cli deploy "Berlin VPS"
    python -m server.cli export "Berlin VPS" --qr

Everything the GUI can do is available here, which is what makes the toolkit
scriptable and testable without a display.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from . import deploy as deploy_mod
from . import backup, export, paths, provision, store
from .model import MODE_NATIVE, MODE_REMOTE, MODES


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "handler", None):
        parser.print_help()
        return 1
    try:
        return args.handler(args)
    except (FileNotFoundError, FileExistsError, ValueError, store.InsecurePermissions) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="server.cli",
        description="Build and operate your own WireGuard + OpenVPN server.",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p = sub.add_parser("init", help="create a new site and generate its keys")
    p.add_argument("name")
    p.add_argument("--mode", choices=MODES, default=MODE_REMOTE)
    p.add_argument("--host", default="", help="public IP or DNS name clients connect to")
    p.add_argument("--ssh", default="", help="user@host for remote deploys")
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--identity", default="", help="path to an SSH private key")
    p.add_argument("--wg-port", type=int, default=None)
    p.add_argument("--ovpn-port", type=int, default=None)
    p.add_argument("--no-openvpn", action="store_true", help="skip the TCP fallback")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(handler=_cmd_init)

    # list
    p = sub.add_parser("list", help="list stored sites")
    p.set_defaults(handler=_cmd_list)

    # show
    p = sub.add_parser("show", help="show a site's configuration and peers")
    p.add_argument("name")
    p.set_defaults(handler=_cmd_show)

    # set
    p = sub.add_parser("set", help="change site settings")
    p.add_argument("name")
    p.add_argument("--host", help="public IP or DNS name (reissues the OpenVPN cert)")
    p.add_argument("--ssh", help="user@host")
    p.add_argument("--ssh-port", type=int)
    p.add_argument("--identity")
    p.add_argument("--dns", help="comma-separated resolvers pushed to clients")
    p.add_argument("--full-tunnel", dest="full_tunnel", action="store_true", default=None)
    p.add_argument("--split-tunnel", dest="full_tunnel", action="store_false")
    p.add_argument("--lan-routes", help="comma-separated CIDRs for split tunnel")
    p.add_argument("--enable-openvpn", action="store_true")
    p.set_defaults(handler=_cmd_set)

    # peer
    p = sub.add_parser("peer", help="manage client devices")
    peer_sub = p.add_subparsers(dest="peer_command")

    q = peer_sub.add_parser("add")
    q.add_argument("site")
    q.add_argument("peer_name")
    q.add_argument("--notes", default="")
    q.set_defaults(handler=_cmd_peer_add)

    q = peer_sub.add_parser("remove")
    q.add_argument("site")
    q.add_argument("peer_name")
    q.set_defaults(handler=_cmd_peer_remove)

    q = peer_sub.add_parser("list")
    q.add_argument("site")
    q.set_defaults(handler=_cmd_peer_list)

    q = peer_sub.add_parser("enable")
    q.add_argument("site")
    q.add_argument("peer_name")
    q.set_defaults(handler=lambda a: _cmd_peer_toggle(a, True))

    q = peer_sub.add_parser("disable")
    q.add_argument("site")
    q.add_argument("peer_name")
    q.set_defaults(handler=lambda a: _cmd_peer_toggle(a, False))

    q = peer_sub.add_parser("rotate", help="replace a peer's keys (lost device)")
    q.add_argument("site")
    q.add_argument("peer_name")
    q.set_defaults(handler=_cmd_peer_rotate)

    # export
    p = sub.add_parser("export", help="write client configs to disk")
    p.add_argument("name")
    p.add_argument("--peer", help="export just this peer")
    p.add_argument("--dir", help="output directory")
    p.add_argument("--qr", action="store_true", help="also print a scannable QR code")
    p.add_argument("--register", action="store_true", help="add to config/vpn_profiles.json")
    p.set_defaults(handler=_cmd_export)

    # script
    p = sub.add_parser("script", help="print the installer script without running it")
    p.add_argument("name")
    p.add_argument("--out", help="write to a file instead of stdout")
    p.add_argument("--teardown", action="store_true", help="print the removal script")
    p.set_defaults(handler=_cmd_script)

    # check
    p = sub.add_parser("check", help="validate a site and test SSH reachability")
    p.add_argument("name")
    p.set_defaults(handler=_cmd_check)

    # deploy
    p = sub.add_parser("deploy", help="apply the configuration to the server")
    p.add_argument("name")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(handler=_cmd_deploy)

    # teardown
    p = sub.add_parser("teardown", help="remove the VPN server from its host")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p.set_defaults(handler=_cmd_teardown)

    # status
    p = sub.add_parser("status", help="ask the server which devices are connected")
    p.add_argument("name")
    p.set_defaults(handler=_cmd_status)

    # backup
    p = sub.add_parser("backup", help="write an encrypted backup of a site")
    p.add_argument("name")
    p.add_argument("--out", help="output file (default: alongside the site state)")
    p.set_defaults(handler=_cmd_backup)

    # restore
    p = sub.add_parser("restore", help="restore a site from an encrypted backup")
    p.add_argument("file")
    p.add_argument("--overwrite", action="store_true",
                   help="replace an existing site of the same name")
    p.set_defaults(handler=_cmd_restore)

    # delete
    p = sub.add_parser("delete", help="delete local site state including all keys")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(handler=_cmd_delete)

    return parser


# ── Handlers ─────────────────────────────────────


def _cmd_init(args) -> int:
    site = provision.init_site(
        args.name,
        args.mode,
        endpoint_host=args.host,
        enable_openvpn=not args.no_openvpn,
        overwrite=args.overwrite,
    )
    if args.ssh:
        _apply_ssh(site, args.ssh, args.ssh_port, args.identity)
    if args.wg_port:
        site.wg_port = args.wg_port
    if args.ovpn_port:
        site.ovpn_port = args.ovpn_port
    store.save_site(site)

    print(f"Created site {site.name!r} ({site.mode}).")
    print(f"  State: {paths.site_file(site.name)}")
    print(f"  Server public key: {site.server_wg_public_key}")
    if not site.endpoint_host:
        print("\nNo endpoint set yet. Clients need one:")
        print(f"  python -m server.cli set {site.name!r} --host <public-ip-or-dns>")
    print(f"\nNext: python -m server.cli peer add {site.name!r} <device-name>")
    return 0


def _cmd_list(args) -> int:
    names = store.list_sites()
    if not names:
        print("No sites yet. Create one with: python -m server.cli init <name>")
        return 0
    for name in names:
        site = store.load_site(name)
        peers = len(site.peers)
        deployed = site.last_deployed_at or "never deployed"
        print(f"{name:<28} {site.mode:<8} {peers:>2} peer(s)  {deployed}")
    return 0


def _cmd_show(args) -> int:
    print(export.site_summary(store.load_site(args.name)))
    return 0


def _cmd_set(args) -> int:
    site = store.load_site(args.name)

    if args.host is not None:
        provision.set_endpoint(site, args.host)
        print(f"Endpoint set to {site.endpoint_host}")
    if args.ssh is not None or args.ssh_port is not None or args.identity is not None:
        _apply_ssh(site, args.ssh, args.ssh_port, args.identity)
    if args.dns is not None:
        site.dns = [d.strip() for d in args.dns.split(",") if d.strip()]
    if args.full_tunnel is not None:
        site.full_tunnel = args.full_tunnel
    if args.lan_routes is not None:
        site.lan_routes = [r.strip() for r in args.lan_routes.split(",") if r.strip()]
    if args.enable_openvpn:
        provision.enable_openvpn(site)

    store.save_site(site)
    print(export.site_summary(site))
    return 0


def _cmd_peer_add(args) -> int:
    site = store.load_site(args.site)
    peer = provision.add_peer(site, args.peer_name, notes=args.notes)
    print(f"Added peer {peer.name!r} at {peer.ip4}")
    if not site.last_deployed_at:
        print("Deploy the site to activate it: python -m server.cli deploy "
              f"{site.name!r}")
    else:
        print("Redeploy to activate it on the server: python -m server.cli deploy "
              f"{site.name!r}")
    return 0


def _cmd_peer_remove(args) -> int:
    site = store.load_site(args.site)
    if provision.remove_peer(site, args.peer_name):
        print(f"Removed {args.peer_name!r}. Redeploy to revoke it on the server.")
        return 0
    print(f"No peer named {args.peer_name!r}", file=sys.stderr)
    return 1


def _cmd_peer_list(args) -> int:
    site = store.load_site(args.site)
    if not site.peers:
        print("(no peers)")
        return 0
    for peer in site.peers:
        state = "enabled " if peer.enabled else "disabled"
        ovpn = "yes" if peer.has_openvpn else "no "
        print(f"{peer.name:<22} {peer.ip4:<15} {state}  ovpn:{ovpn}  {peer.created_at}")
    return 0


def _cmd_peer_toggle(args, enabled: bool) -> int:
    site = store.load_site(args.site)
    if provision.set_peer_enabled(site, args.peer_name, enabled):
        print(f"{args.peer_name!r} {'enabled' if enabled else 'disabled'}. Redeploy to apply.")
        return 0
    print(f"No peer named {args.peer_name!r}", file=sys.stderr)
    return 1


def _cmd_peer_rotate(args) -> int:
    site = store.load_site(args.site)
    provision.rotate_peer_keys(site, args.peer_name)
    print(f"Rotated keys for {args.peer_name!r}.")
    print("The old config no longer works after the next deploy.")
    print(f"Re-export and re-deliver: python -m server.cli export {site.name!r} "
          f"--peer {args.peer_name!r}")
    return 0


def _cmd_export(args) -> int:
    site = store.load_site(args.name)
    directory = Path(args.dir).expanduser() if args.dir else None

    peers = [site.get_peer(args.peer)] if args.peer else list(site.peers)
    if args.peer and peers[0] is None:
        print(f"No peer named {args.peer!r}", file=sys.stderr)
        return 1
    if not peers:
        print("Site has no peers to export.", file=sys.stderr)
        return 1

    for peer in peers:
        written = export.export_peer(site, peer, directory=directory)
        print(f"{peer.name}:")
        for kind, path in written.items():
            print(f"  {kind:<10} {path}")
        if args.qr:
            print(export.qr_terminal(site, peer))

    if args.register:
        changed = export.register_profile(site)
        print("Registered in config/vpn_profiles.json" if changed else "Profile already current.")

    print("\nThese files contain private keys. Delete them once imported.")
    return 0


def _cmd_script(args) -> int:
    site = store.load_site(args.name)
    text = (
        deploy_mod.build_teardown_script(site)
        if args.teardown
        else deploy_mod.build_script(site)
    )
    if args.out:
        out = Path(args.out).expanduser()
        paths.write_private(out, text)
        out.chmod(0o700)
        print(f"Wrote {out}")
        print("It embeds private keys — run it, then delete it.")
    else:
        print(text)
    return 0


def _cmd_check(args) -> int:
    site = store.load_site(args.name)
    problems = deploy_mod.preflight(site)

    if problems:
        print("Blocking problems:")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("Site configuration is valid.")

    if site.mode == MODE_REMOTE and site.ssh.is_configured():
        print(f"\nTesting SSH to {site.ssh.destination()}…")
        result = deploy_mod.check_ssh(site)
        if result.success:
            print("  reachable, and we can act as root.")
        else:
            print(f"  {result.summary()}")
            for problem in result.problems:
                print(f"  - {problem}")
            return 1

    return 1 if problems else 0


def _cmd_deploy(args) -> int:
    site = store.load_site(args.name)
    result = deploy_mod.deploy(site, dry_run=args.dry_run, on_output=print)

    if args.dry_run:
        print(result.output)
        return 0
    if result.success:
        print(f"\n{result.summary()}")
        return 0

    print(f"\n{result.summary()}", file=sys.stderr)
    for problem in result.problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def _cmd_teardown(args) -> int:
    site = store.load_site(args.name)
    if not args.yes and not _confirm(
        f"Remove the VPN server from {site.ssh.destination()}? Every client "
        "loses connectivity."
    ):
        print("Cancelled.")
        return 1
    result = deploy_mod.teardown(site, on_output=print)
    if result.success:
        print("\nTeardown complete. Local site state was kept.")
        return 0
    print(f"\n{result.summary()}", file=sys.stderr)
    return 1


def _cmd_delete(args) -> int:
    if not args.yes and not _confirm(
        f"Delete all local state for {args.name!r}? This destroys the only copy "
        "of the server and CA private keys, and no client config can ever be "
        "reissued."
    ):
        print("Cancelled.")
        return 1
    if store.delete_site(args.name):
        print(f"Deleted {args.name!r}.")
        return 0
    print(f"No site named {args.name!r}", file=sys.stderr)
    return 1


def _cmd_status(args) -> int:
    site = store.load_site(args.name)
    status = deploy_mod.server_status(site)

    if not status.reachable:
        print(status.summary(), file=sys.stderr)
        return 1

    print(status.summary())
    if not status.peers:
        print("\n(no peers configured on the server)")
        return 0

    print(f"\n{'DEVICE':<22} {'HANDSHAKE':<12} {'TRANSFER':<26} ENDPOINT")
    for peer in status.peers:
        mark = "*" if peer.connected else " "
        print(f"{mark}{peer.name:<21} {peer.describe_handshake():<12} "
              f"{peer.describe_transfer():<26} {peer.endpoint or '-'}")
    print("\n* = handshaked within the last ~3 minutes")
    return 0


def _cmd_backup(args) -> int:
    site = store.load_site(args.name)

    passphrase = _ask_passphrase(confirm=True)
    if passphrase is None:
        return 1

    target = Path(args.out).expanduser() if args.out else (
        paths.state_dir() / f"{paths.slugify(site.name)}{backup.SUFFIX}"
    )
    written = backup.write_backup(site, passphrase, target)

    print(f"Wrote {written}")
    print("Holds the server key and the certificate authority, encrypted.")
    print("Without the passphrase it cannot be opened — including by you.")
    return 0


def _cmd_restore(args) -> int:
    path = Path(args.file).expanduser()
    if not path.is_file():
        print(f"No such file: {path}", file=sys.stderr)
        return 1

    try:
        info = backup.describe(path.read_bytes())
    except backup.BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Backup of site {info['site']!r} (format v{info['version']})")

    passphrase = _ask_passphrase(confirm=False)
    if passphrase is None:
        return 1

    try:
        site = backup.restore(path, passphrase, overwrite=args.overwrite)
    except backup.BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Restored {site.name!r} with {len(site.peers)} peer(s).")
    print("Deploy it to make the server match this state again.")
    return 0


def _ask_passphrase(*, confirm: bool) -> str | None:
    """
    Read a passphrase without echoing it.

    getpass reads from the terminal directly, so the passphrase never reaches
    the shell history, the process list, or any log.
    """
    try:
        passphrase = getpass.getpass("Passphrase: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    if not passphrase:
        print("Empty passphrase — aborting.", file=sys.stderr)
        return None

    if confirm:
        for problem in backup.passphrase_problems(passphrase):
            print(f"warning: {problem}", file=sys.stderr)
        if getpass.getpass("Repeat: ") != passphrase:
            print("Passphrases do not match.", file=sys.stderr)
            return None
    return passphrase


# ── Helpers ──────────────────────────────────────


def _apply_ssh(site, destination: str | None, port: int | None, identity: str | None) -> None:
    if destination:
        if "@" in destination:
            user, _, host = destination.partition("@")
            site.ssh.user, site.ssh.host = user, host
        else:
            site.ssh.host = destination
    if port:
        site.ssh.port = port
    if identity:
        site.ssh.identity_file = str(Path(identity).expanduser())


def _confirm(question: str) -> bool:
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


if __name__ == "__main__":
    sys.exit(main())
