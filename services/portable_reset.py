"""Narrow, guarded deletion of Sentinel-owned portable state."""
from __future__ import annotations

import shutil
from pathlib import Path

from services.runtime_paths import (
    PORTABLE_DATA_DIR, PORTABLE_MARKER, PortableRuntimeError,
    portable_root, user_data_base,
)

CONFIRMATION_PHRASE = "ERASE SENTINEL DATA"


def erase_portable_user_data() -> Path:
    """Delete only the marked portable data directory's contents.

    This is deliberately unavailable for development and normal installed
    builds. It does not format a volume or attempt to erase operating-system,
    network, provider, swap, or forensic records.
    """
    root = portable_root()
    if root is None:
        raise PortableRuntimeError("Emergency Reset is available only in USB-portable mode.")
    root = root.resolve()
    if not (root / PORTABLE_MARKER).is_file():
        raise PortableRuntimeError("Portable marker is missing; reset was refused.")
    data = user_data_base().resolve()
    expected = (root / PORTABLE_DATA_DIR).resolve()
    if data != expected or data.parent != root:
        raise PortableRuntimeError("Portable data path failed its safety check; reset was refused.")
    if not data.is_dir():
        raise PortableRuntimeError("Portable data folder is unavailable; reset was refused.")

    for child in tuple(data.iterdir()):
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    return data
