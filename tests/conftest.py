"""Session-wide isolation for tests that initialize the application database."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


_TEST_ROOT: Path | None = None


@pytest.fixture(scope="session", autouse=True)
def _session_qapplication():
    """Keep one Qt application alive across modules that construct widgets."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    yield application


def pytest_configure(config):
    """Redirect SQLite before test modules import application services.

    BASE_DIR deliberately remains the project root so a fresh test database is
    seeded from the same checked-in config as a development launch. Only the
    writable database is redirected.
    """
    global _TEST_ROOT
    _TEST_ROOT = Path(tempfile.mkdtemp(prefix="sentinel-fork-tests-"))

    from services import database

    database.DB_PATH = _TEST_ROOT / "data" / "sentinel.db"
    database.init_db()


def pytest_unconfigure(config):
    global _TEST_ROOT
    if _TEST_ROOT is not None:
        shutil.rmtree(_TEST_ROOT, ignore_errors=True)
        _TEST_ROOT = None
