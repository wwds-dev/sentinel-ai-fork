from pathlib import Path

import pytest

from services import portable_reset
from services.runtime_paths import PORTABLE_DATA_DIR, PORTABLE_MARKER, PortableRuntimeError


def portable_tree(tmp_path, monkeypatch):
    root = tmp_path / "portable"
    data = root / PORTABLE_DATA_DIR
    data.mkdir(parents=True)
    (root / PORTABLE_MARKER).touch()
    monkeypatch.setattr(portable_reset, "portable_root", lambda: root)
    monkeypatch.setattr(portable_reset, "user_data_base", lambda: data)
    return root, data


def test_reset_deletes_only_portable_sentinel_data(tmp_path, monkeypatch):
    root, data = portable_tree(tmp_path, monkeypatch)
    outside = root / "family-photos.txt"
    outside.write_text("keep")
    (data / ".env").write_text("SECRET=fake")
    (data / "data" / "logs").mkdir(parents=True)
    (data / "data" / "logs" / "runs.jsonl").write_text("session")

    assert portable_reset.erase_portable_user_data() == data
    assert list(data.iterdir()) == []
    assert outside.read_text() == "keep"
    assert (root / PORTABLE_MARKER).exists()


def test_reset_unlinks_symlink_without_touching_target(tmp_path, monkeypatch):
    _, data = portable_tree(tmp_path, monkeypatch)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    (data / "link").symlink_to(outside)
    portable_reset.erase_portable_user_data()
    assert outside.read_text() == "keep"


def test_reset_is_refused_outside_portable_mode(monkeypatch):
    monkeypatch.setattr(portable_reset, "portable_root", lambda: None)
    with pytest.raises(PortableRuntimeError, match="only in USB-portable mode"):
        portable_reset.erase_portable_user_data()


def test_reset_is_refused_without_marker(tmp_path, monkeypatch):
    root = tmp_path / "portable"
    data = root / PORTABLE_DATA_DIR
    data.mkdir(parents=True)
    monkeypatch.setattr(portable_reset, "portable_root", lambda: root)
    monkeypatch.setattr(portable_reset, "user_data_base", lambda: data)
    with pytest.raises(PortableRuntimeError, match="marker is missing"):
        portable_reset.erase_portable_user_data()
