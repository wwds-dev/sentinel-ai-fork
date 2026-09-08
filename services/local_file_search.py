"""Read-only, bounded local file discovery for Bloodhound."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


DEFAULT_MAX_RESULTS = 5_000
DEFAULT_MAX_ENTRIES = 250_000


@dataclass(frozen=True)
class FileSearchFilters:
    name: str = ""
    exact_name: bool = False
    extensions: tuple[str, ...] = ()
    min_size: int | None = None
    max_size: int | None = None
    modified_after: datetime | None = None
    modified_before: datetime | None = None


@dataclass(frozen=True)
class FileMatch:
    name: str
    path: str
    extension: str
    size: int
    modified: datetime


@dataclass
class FileSearchReport:
    matches: list[FileMatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    entries_checked: int = 0
    cancelled: bool = False
    limit_reached: bool = False


def normalise_extensions(value: str | Iterable[str]) -> tuple[str, ...]:
    """Return lower-case extensions with a leading dot and no duplicates."""
    values = value.replace(";", ",").split(",") if isinstance(value, str) else value
    result: list[str] = []
    for item in values:
        ext = str(item).strip().lower()
        if not ext:
            continue
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext not in result:
            result.append(ext)
    return tuple(result)


def matches_filters(path: Path, stat: os.stat_result, filters: FileSearchFilters) -> bool:
    candidate = path.name.casefold()
    query = filters.name.strip().casefold()
    if query:
        if filters.exact_name and candidate != query:
            return False
        if not filters.exact_name and query not in candidate:
            return False
    if filters.extensions and path.suffix.casefold() not in filters.extensions:
        return False
    if filters.min_size is not None and stat.st_size < filters.min_size:
        return False
    if filters.max_size is not None and stat.st_size > filters.max_size:
        return False
    modified = datetime.fromtimestamp(stat.st_mtime)
    if filters.modified_after and modified < filters.modified_after:
        return False
    if filters.modified_before and modified > filters.modified_before:
        return False
    return True


def search_files(
    roots: Iterable[str | Path],
    filters: FileSearchFilters,
    *,
    should_cancel: Callable[[], bool] = lambda: False,
    on_progress: Callable[[int, int], None] | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> FileSearchReport:
    """Recursively search selected roots without reading or changing file contents."""
    report = FileSearchReport()
    stack: list[Path] = []
    seen: set[str] = set()
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        key = os.path.normcase(os.path.abspath(root))
        if key in seen:
            continue
        seen.add(key)
        if not root.exists():
            report.errors.append(f"Folder does not exist: {root}")
        elif not root.is_dir():
            report.errors.append(f"Not a folder: {root}")
        else:
            stack.append(root)

    while stack:
        if should_cancel():
            report.cancelled = True
            break
        folder = stack.pop()
        try:
            entries = os.scandir(folder)
        except OSError as exc:
            report.errors.append(f"Cannot access {folder}: {exc.strerror or exc}")
            continue
        with entries:
            for entry in entries:
                if should_cancel():
                    report.cancelled = True
                    return report
                report.entries_checked += 1
                if report.entries_checked > max_entries:
                    report.limit_reached = True
                    return report
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    stat = entry.stat(follow_symlinks=False)
                except OSError as exc:
                    report.errors.append(
                        f"Cannot inspect {entry.path}: {exc.strerror or exc}"
                    )
                    continue
                path = Path(entry.path)
                if on_progress and report.entries_checked % 250 == 0:
                    on_progress(report.entries_checked, len(report.matches))
                if not matches_filters(path, stat, filters):
                    continue
                report.matches.append(FileMatch(
                    name=path.name,
                    path=str(path),
                    extension=path.suffix.lower() or "—",
                    size=stat.st_size,
                    modified=datetime.fromtimestamp(stat.st_mtime),
                ))
                if len(report.matches) >= max_results:
                    report.limit_reached = True
                    return report
    if on_progress:
        on_progress(report.entries_checked, len(report.matches))
    return report
