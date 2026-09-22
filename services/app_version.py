"""Canonical Sentinel application-version helpers.

The checked-in ``VERSION`` file is the only source of the public version. It is
bundled by PyInstaller and read by the live development launcher, so the same
value appears in the UI and in every distribution path.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


VERSION_PATTERN = re.compile(r"^[1-9]\d*\.\d{3}$")


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def read_app_version(root: Path | None = None) -> str:
    """Return and validate the public ``MAJOR.SEQUENCE`` application version."""
    version_file = (root or _resource_root()) / "VERSION"
    try:
        version = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"Sentinel version file is unavailable: {version_file}") from exc
    if not VERSION_PATTERN.fullmatch(version):
        raise RuntimeError(
            f"Invalid Sentinel version {version!r}; expected MAJOR.SEQUENCE "
            "such as 2.001"
        )
    return version


APP_VERSION = read_app_version()
DISPLAY_VERSION = f"v{APP_VERSION}"


def build_description(root: Path | None = None) -> str:
    """Describe the exact checkout for diagnostics without changing its version.

    Frozen releases intentionally show only the immutable public version. A
    live development checkout also reports its Git revision and whether local
    changes are present, which distinguishes launches at the same milestone.
    """
    if getattr(sys, "frozen", False):
        return f"Sentinel {DISPLAY_VERSION} · packaged release"

    project_root = root or _resource_root()
    try:
        revision = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--short=8", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain=v1"],
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        ).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return f"Sentinel {DISPLAY_VERSION} · development checkout"

    suffix = " · local changes" if dirty else ""
    return f"Sentinel {DISPLAY_VERSION} · development {revision}{suffix}"
