#!/usr/bin/env python3
"""Render current Sentinel screens for the Learning Centre.

The capture uses an isolated temporary database and Qt's off-screen platform,
so it never exposes real chat history, keys, targets or local paths.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from services import database


OUTPUTS = {
    "chat": "workspace-chat.png",
    "osint": "trace.png",
    "osint_heavy": "bloodhound.png",
    "wifi": "beacon.png",
    "bug_bounty": "bug-spray.png",
    "vpn": "tunnel.png",
    "manager": "forge.png",
}


def settle(app: QApplication, widget) -> None:
    widget.layout().activate()
    for _ in range(8):
        app.processEvents()


def main() -> int:
    output_dir = ROOT / "docs" / "training" / "images"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Agent selection updates the preferred-model seed during a normal run.
    # A documentation capture must not change the developer's real defaults.
    settings_path = ROOT / "config" / "settings.json"
    settings_snapshot = settings_path.read_bytes() if settings_path.exists() else None

    try:
        with tempfile.TemporaryDirectory(prefix="sentinel-training-") as tmp:
            database.DB_PATH = Path(tmp) / "sentinel.db"
            database.init_db()

            import main as sentinel_main
            from ui.learning_center import build_learning_center

            app = QApplication.instance() or QApplication([])
            window = sentinel_main.GodAI()
            window.setAttribute(Qt.WA_DontShowOnScreen, True)
            window.resize(1600, 1000)
            window.show()

            for agent, filename in OUTPUTS.items():
                window.select_agent(agent)
                settle(app, window)
                if not window.grab().save(str(output_dir / filename)):
                    raise RuntimeError(f"Could not save {filename}")

            learning = build_learning_center(window)
            learning.setAttribute(Qt.WA_DontShowOnScreen, True)
            learning.resize(1120, 760)
            learning.show()
            settle(app, learning)
            if not learning.grab().save(str(output_dir / "learning-centre.png")):
                raise RuntimeError("Could not save learning-centre.png")
            learning.close()
            window.close()
    finally:
        if settings_snapshot is not None:
            settings_path.write_bytes(settings_snapshot)

    print(f"Captured {len(OUTPUTS) + 1} training screenshots in {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
