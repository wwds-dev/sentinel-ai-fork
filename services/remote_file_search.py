"""Authenticated, read-only SFTP discovery for explicitly configured hosts."""

from __future__ import annotations

import posixpath
import socket
import stat
from datetime import datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from typing import Callable, Iterable

from services.local_file_search import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_MAX_RESULTS,
    FileMatch,
    FileSearchFilters,
    FileSearchReport,
    matches_filters,
)


def validate_ssh_target(host: str, username: str, port: int) -> None:
    if not host or any(char.isspace() for char in host):
        raise ValueError("Enter a valid SSH hostname, IP address, or config alias.")
    if not username or any(char.isspace() for char in username):
        raise ValueError("Enter a valid SSH username.")
    if not 1 <= port <= 65535:
        raise ValueError("SSH port must be between 1 and 65535.")


def _connect(host: str, username: str, port: int):
    try:
        import paramiko
    except ImportError as exc:
        raise RuntimeError(
            "Remote search needs Paramiko. Install the updated project requirements."
        ) from exc

    lookup: dict = {}
    config_path = Path.home() / ".ssh" / "config"
    if config_path.exists():
        with config_path.open(encoding="utf-8") as handle:
            config = paramiko.SSHConfig()
            config.parse(handle)
            lookup = config.lookup(host)
    resolved_host = lookup.get("hostname", host)
    resolved_user = lookup.get("user", username)
    resolved_port = int(lookup.get("port", port))
    sock = None
    if lookup.get("proxycommand"):
        sock = paramiko.ProxyCommand(lookup["proxycommand"])

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        hostname=resolved_host,
        port=resolved_port,
        username=resolved_user,
        allow_agent=True,
        look_for_keys=True,
        password=None,
        timeout=12,
        banner_timeout=12,
        auth_timeout=12,
        sock=sock,
    )
    return client


def search_remote_files(
    host: str,
    username: str,
    port: int,
    roots: Iterable[str],
    filters: FileSearchFilters,
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    on_progress: Callable[[int, int], None] | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> FileSearchReport:
    """Walk remote folders over SFTP; no remote command or file content is used."""
    validate_ssh_target(host, username, port)
    clean_roots = []
    for raw in roots:
        root = str(raw).strip()
        if not root or not root.startswith("/") or "\x00" in root:
            raise ValueError("Every remote folder must be an absolute path.")
        clean_roots.append(posixpath.normpath(root))
    if not clean_roots:
        raise ValueError("Enter at least one remote folder.")

    report = FileSearchReport()
    client = _connect(host, username, port)
    try:
        sftp = client.open_sftp()
        try:
            stack = list(dict.fromkeys(clean_roots))
            while stack:
                if should_cancel():
                    report.cancelled = True
                    break
                folder = stack.pop()
                try:
                    entries = sftp.listdir_attr(folder)
                except (OSError, IOError, socket.error) as exc:
                    report.errors.append(f"Cannot access {folder}: {exc}")
                    continue
                for entry in entries:
                    if should_cancel():
                        report.cancelled = True
                        return report
                    report.entries_checked += 1
                    if report.entries_checked > max_entries:
                        report.limit_reached = True
                        return report
                    remote_path = posixpath.join(folder, entry.filename)
                    mode = entry.st_mode or 0
                    if stat.S_ISLNK(mode):
                        continue
                    if stat.S_ISDIR(mode):
                        stack.append(remote_path)
                        continue
                    if not stat.S_ISREG(mode):
                        continue
                    if on_progress and report.entries_checked % 250 == 0:
                        on_progress(report.entries_checked, len(report.matches))
                    path = PurePosixPath(remote_path)
                    metadata = SimpleNamespace(
                        st_size=int(entry.st_size or 0),
                        st_mtime=float(entry.st_mtime or 0),
                    )
                    if not matches_filters(path, metadata, filters):
                        continue
                    report.matches.append(FileMatch(
                        name=entry.filename,
                        path=remote_path,
                        extension=path.suffix.lower() or "—",
                        size=metadata.st_size,
                        modified=datetime.fromtimestamp(metadata.st_mtime),
                    ))
                    if len(report.matches) >= max_results:
                        report.limit_reached = True
                        return report
        finally:
            sftp.close()
    finally:
        client.close()
    if on_progress:
        on_progress(report.entries_checked, len(report.matches))
    return report
