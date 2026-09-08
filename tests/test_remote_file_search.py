import stat
from types import SimpleNamespace

import pytest

from services.local_file_search import FileSearchFilters
from services import remote_file_search


class FakeSftp:
    def __init__(self):
        self.closed = False

    def listdir_attr(self, folder):
        if folder == "/allowed":
            return [
                SimpleNamespace(
                    filename="nested", st_mode=stat.S_IFDIR | 0o755,
                    st_size=0, st_mtime=1_700_000_000,
                ),
                SimpleNamespace(
                    filename="report.pdf", st_mode=stat.S_IFREG | 0o644,
                    st_size=2048, st_mtime=1_700_000_000,
                ),
                SimpleNamespace(
                    filename="link", st_mode=stat.S_IFLNK | 0o777,
                    st_size=0, st_mtime=1_700_000_000,
                ),
            ]
        if folder == "/allowed/nested":
            return [SimpleNamespace(
                filename="notes.txt", st_mode=stat.S_IFREG | 0o644,
                st_size=20, st_mtime=1_700_000_000,
            )]
        raise PermissionError("denied")

    def close(self):
        self.closed = True


class FakeClient:
    def __init__(self):
        self.sftp = FakeSftp()
        self.closed = False

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


def test_remote_search_uses_sftp_filters_and_skips_links(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(remote_file_search, "_connect", lambda *args: client)
    report = remote_file_search.search_remote_files(
        "owned-host", "analyst", 22, ["/allowed"],
        FileSearchFilters(extensions=(".pdf",)),
    )
    assert [match.path for match in report.matches] == ["/allowed/report.pdf"]
    assert client.sftp.closed is True
    assert client.closed is True


def test_remote_search_reports_inaccessible_roots_and_keeps_results(monkeypatch):
    monkeypatch.setattr(remote_file_search, "_connect", lambda *args: FakeClient())
    report = remote_file_search.search_remote_files(
        "owned-host", "analyst", 22, ["/blocked", "/allowed"],
        FileSearchFilters(),
    )
    assert {match.name for match in report.matches} == {"report.pdf", "notes.txt"}
    assert "Cannot access /blocked" in report.errors[0]


@pytest.mark.parametrize("root", ["relative/path", "", "../escape"])
def test_remote_roots_must_be_absolute(monkeypatch, root):
    with pytest.raises(ValueError, match="absolute path"):
        remote_file_search.search_remote_files(
            "owned-host", "analyst", 22, [root], FileSearchFilters()
        )


def test_invalid_host_user_and_port_are_rejected_before_connection():
    with pytest.raises(ValueError):
        remote_file_search.validate_ssh_target("bad host", "analyst", 22)
    with pytest.raises(ValueError):
        remote_file_search.validate_ssh_target("server", "bad user", 22)
    with pytest.raises(ValueError):
        remote_file_search.validate_ssh_target("server", "analyst", 70000)
