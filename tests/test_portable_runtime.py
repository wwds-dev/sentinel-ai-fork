from pathlib import Path

import pytest

from services import runtime_paths


def test_explicit_portable_root_uses_dedicated_data_folder(tmp_path):
    root = runtime_paths.portable_root_from_environment(
        {runtime_paths.PORTABLE_ENV: str(tmp_path)}
    )
    assert root == tmp_path.resolve()
    assert runtime_paths.portable_data_base(root) == tmp_path / "Sentinel Data"


def test_marked_frozen_bundle_is_detected(monkeypatch, tmp_path):
    executable = tmp_path / "Sentinel.app" / "Contents" / "MacOS" / "Sentinel"
    executable.parent.mkdir(parents=True)
    executable.touch()
    (tmp_path / runtime_paths.PORTABLE_MARKER).touch()
    monkeypatch.delenv(runtime_paths.PORTABLE_ENV, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_paths.sys, "executable", str(executable))
    assert runtime_paths.portable_root() == tmp_path


def test_missing_portable_volume_has_clear_error(tmp_path):
    missing = tmp_path / "ejected"
    with pytest.raises(runtime_paths.PortableRuntimeError, match="ejected"):
        runtime_paths.validate_portable_volume(missing)


def test_low_space_has_clear_error(monkeypatch, tmp_path):
    usage = runtime_paths.shutil._ntuple_diskusage(100, 100, 0)
    monkeypatch.setattr(runtime_paths.shutil, "disk_usage", lambda _path: usage)
    with pytest.raises(runtime_paths.PortableRuntimeError, match="low on space"):
        runtime_paths.validate_portable_volume(tmp_path, min_free_bytes=1)


def test_portable_builder_never_references_source_env_contents():
    script = (Path(__file__).parents[1] / "scripts" / "build_portable.sh").read_text()
    assert 'cp "${PROJECT_ROOT}/.env.example"' in script
    assert 'cp "${PROJECT_ROOT}/.env"' not in script
    assert '${APP_NAME} Data' in script


def test_portable_state_is_renamed_from_the_legacy_folder(tmp_path):
    legacy = tmp_path / "Sentinel Fork Data"
    legacy.mkdir()
    (legacy / "keep.txt").write_text("user state", encoding="utf-8")

    current = runtime_paths.validate_portable_volume(
        tmp_path, min_free_bytes=0, probe=False
    )

    assert current == tmp_path / "Sentinel Data"
    assert (current / "keep.txt").read_text(encoding="utf-8") == "user state"
    assert not legacy.exists()


def test_normal_state_is_renamed_from_the_legacy_folder(tmp_path):
    legacy = tmp_path / "Sentinel Fork"
    legacy.mkdir()
    (legacy / "sentinel.db").write_bytes(b"database")

    current = runtime_paths._migrate_legacy_directory(
        tmp_path, runtime_paths.APP_NAME, runtime_paths.LEGACY_APP_NAMES
    )

    assert current == tmp_path / "Sentinel"
    assert (current / "sentinel.db").read_bytes() == b"database"
    assert not legacy.exists()
