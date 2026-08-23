"""Writable services must not depend on the launcher's working directory."""

from pathlib import Path


def test_default_chat_and_report_paths_ignore_cwd(tmp_path, monkeypatch):
    from services import history_store, report_exporter

    user_root = tmp_path / "sentinel-user-data"
    unrelated = tmp_path / "unrelated-cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(history_store, "user_data_base", lambda: user_root)
    monkeypatch.setattr(report_exporter, "user_data_base", lambda: user_root)

    history = history_store.HistoryStore()
    chat = history.save_chat("chat", "ollama", "model", "", [], "hello")
    reports = report_exporter.ReportExporter()
    report = reports.export_text_report("Trace result", "content")

    assert chat.parent == user_root / "data" / "chats"
    assert report.parent == user_root / "data" / "reports"
    assert not (unrelated / "data").exists()


def test_report_exports_do_not_overwrite_on_filename_collision(tmp_path, monkeypatch):
    from services import report_exporter

    class FixedDateTime:
        @classmethod
        def now(cls):
            return cls()

        def strftime(self, _format):
            return "same-time"

    values = iter(["first", "second"])

    class FakeUuid:
        @property
        def hex(self):
            return next(values)

    monkeypatch.setattr(report_exporter, "datetime", FixedDateTime)
    monkeypatch.setattr(report_exporter, "uuid4", lambda: FakeUuid())
    exporter = report_exporter.ReportExporter(tmp_path)

    first = exporter.export_text_report("same", "one")
    second = exporter.export_text_report("same", "two")

    assert first != second
    assert first.read_text() == "one"
    assert second.read_text() == "two"
