"""
paths.py — Where server state lives on disk.

Key material must never sit inside the repo (it would be one `git add -A` away
from a public push) and never inside a frozen .app bundle (that breaks the code
signature and a reinstall wipes it). Everything goes to the per-user
application-support directory with restrictive permissions.

Override with VPN_AGENT_STATE_DIR — useful for tests and for keeping a site on
an encrypted volume.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

APP_NAME = "VPN Agent"
ENV_STATE_DIR = "VPN_AGENT_STATE_DIR"

DIR_MODE = 0o700
FILE_MODE = 0o600


def state_dir() -> Path:
    """Root directory for all VPN Agent state that must survive reinstalls."""
    override = os.environ.get(ENV_STATE_DIR)
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "vpn-agent"


def sites_dir() -> Path:
    """Directory holding one JSON file per VPN site."""
    return state_dir() / "sites"


def site_file(site_name: str) -> Path:
    """Path to a single site's state file."""
    return sites_dir() / f"{slugify(site_name)}.json"


def exports_dir(site_name: str) -> Path:
    """Directory where generated client configs for a site are written."""
    return state_dir() / "exports" / slugify(site_name)


def profiles_file() -> Path:
    """
    The client-side profile list, in a location the app may actually write to.

    This file is written at runtime — selecting a profile persists it, and
    registering a built server appends to it. The copy shipped in config/ is a
    read-only seed: once frozen it lives inside the .app bundle, where writing
    would break the code signature and a reinstall would silently discard every
    profile the user had added.
    """
    return state_dir() / "vpn_profiles.json"


def slugify(name: str) -> str:
    """Reduce a display name to something safe for a filename or interface."""
    out = []
    for ch in name.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_.":
            out.append("-")
    slug = "".join(out).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "site"


def ensure_private_dir(path: Path) -> Path:
    """Create a directory (and parents) that only this user can read."""
    path.mkdir(parents=True, exist_ok=True)
    _harden_dir(path)
    # Parents inside our own state dir get hardened too; anything above is the
    # user's own home layout and is left alone.
    root = state_dir()
    for parent in path.parents:
        if parent == root or root in parent.parents:
            _harden_dir(parent)
        if parent == root:
            break
    return path


def write_private(path: Path, text: str) -> Path:
    """
    Write a file containing secrets so that only this user can read it.

    The mode is set before the content lands, so there is no window in which
    the key material is world-readable.
    """
    ensure_private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    finally:
        # os.fdopen owns the fd now; if it raised before taking ownership the
        # descriptor is already closed by the failure path.
        pass
    os.chmod(path, FILE_MODE)
    return path


def _harden_dir(path: Path) -> None:
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != DIR_MODE:
            os.chmod(path, DIR_MODE)
    except OSError:
        # A directory we do not own (or a race with another process) is not
        # worth crashing over — the file mode is the real protection.
        pass
