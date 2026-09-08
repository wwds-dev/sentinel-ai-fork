from datetime import datetime, timedelta
from pathlib import Path

from services.local_file_search import (
    FileSearchFilters,
    normalise_extensions,
    search_files,
)


def test_extension_and_partial_name_filters_are_case_insensitive(tmp_path):
    (tmp_path / "Quarterly Report.PDF").write_text("report")
    (tmp_path / "quarterly-notes.txt").write_text("notes")
    report = search_files(
        [tmp_path],
        FileSearchFilters(name="REPORT", extensions=(".pdf",)),
    )
    assert [match.name for match in report.matches] == ["Quarterly Report.PDF"]


def test_exact_name_size_and_modified_date_filters(tmp_path):
    target = tmp_path / "archive.zip"
    target.write_bytes(b"x" * 50)
    now = datetime.now()
    report = search_files(
        [tmp_path],
        FileSearchFilters(
            name="archive.zip",
            exact_name=True,
            min_size=40,
            max_size=60,
            modified_after=now - timedelta(minutes=1),
            modified_before=now + timedelta(minutes=1),
        ),
    )
    assert len(report.matches) == 1
    assert report.matches[0].size == 50


def test_search_is_recursive_and_does_not_follow_directory_symlinks(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "inside.txt").write_text("inside")
    link = tmp_path / "loop"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pass
    report = search_files([tmp_path], FileSearchFilters())
    assert [match.name for match in report.matches] == ["inside.txt"]


def test_missing_roots_are_reported_without_blocking_valid_roots(tmp_path):
    (tmp_path / "found.md").write_text("ok")
    report = search_files(
        [tmp_path / "missing", tmp_path], FileSearchFilters(extensions=(".md",))
    )
    assert [match.name for match in report.matches] == ["found.md"]
    assert "Folder does not exist" in report.errors[0]


def test_cancellation_and_safety_limits_return_partial_reports(tmp_path):
    for index in range(5):
        (tmp_path / f"{index}.txt").write_text("x")
    limited = search_files([tmp_path], FileSearchFilters(), max_results=2)
    assert len(limited.matches) == 2
    assert limited.limit_reached is True

    cancelled = search_files(
        [tmp_path], FileSearchFilters(), should_cancel=lambda: True
    )
    assert cancelled.cancelled is True
    assert cancelled.matches == []


def test_extension_input_is_normalised_and_deduplicated():
    assert normalise_extensions("PDF, .jpg; pdf") == (".pdf", ".jpg")


def test_search_only_reads_metadata_and_leaves_files_unchanged(tmp_path):
    file = tmp_path / "private.txt"
    file.write_text("secret content")
    before = (file.read_bytes(), file.stat().st_mtime_ns)
    search_files([tmp_path], FileSearchFilters(name="private"))
    after = (file.read_bytes(), file.stat().st_mtime_ns)
    assert after == before
