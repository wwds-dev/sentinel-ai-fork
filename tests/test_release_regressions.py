"""Regression checks for release-blocking routing, usage, and history bugs."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest


class _TextValue:
    def __init__(self, value):
        self.value = value

    def currentText(self):
        return self.value


class _CheckValue:
    def __init__(self, checked):
        self.checked = checked

    def isChecked(self):
        return self.checked


def _routing_stub(mode: str, qwen_enabled: bool):
    return SimpleNamespace(
        provider_box=_TextValue("qwen"),
        model_box=_TextValue("qwen3-max"),
        execution_mode_box=_TextValue(mode),
        allow_openai_checkbox=_CheckValue(False),
        allow_deepseek_checkbox=_CheckValue(False),
        allow_kimi_checkbox=_CheckValue(False),
        allow_gemini_checkbox=_CheckValue(False),
        allow_anthropic_checkbox=_CheckValue(False),
        allow_qwen_checkbox=_CheckValue(qwen_enabled),
    )


@pytest.mark.parametrize("mode", ["Cloud only", "Hybrid allowed"])
def test_qwen_routes_when_its_permission_is_enabled(mode):
    from main import GodAI

    assert GodAI.resolve_backend_model(_routing_stub(mode, True)) == ("qwen", "qwen3-max")


@pytest.mark.parametrize("mode", ["Cloud only", "Hybrid allowed"])
def test_qwen_is_blocked_when_its_permission_is_disabled(mode):
    from main import GodAI

    with pytest.raises(RuntimeError, match="qwen API is not enabled"):
        GodAI.resolve_backend_model(_routing_stub(mode, False))


def test_two_chats_saved_immediately_never_overwrite(tmp_path):
    from services.history_store import HistoryStore

    history = HistoryStore(tmp_path)
    first = history.save_chat("chat", "ollama", "local", "", [], "first")
    second = history.save_chat("chat", "ollama", "local", "", [], "second")

    assert first != second
    assert first.exists() and second.exists()
    assert len(history.list_chats()) == 2


@pytest.mark.parametrize(
    ("backend", "expected"),
    [
        ("ollama", False),
        ("openai", True),
        ("deepseek", True),
        ("kimi", True),
        ("gemini", True),
        ("anthropic", True),
        ("qwen", True),
    ],
)
def test_usage_cloud_flag_covers_every_supported_provider(tmp_path, monkeypatch, backend, expected):
    from services import usage_tracker as usage_module

    db_path = tmp_path / "usage.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE pricing (
                backend TEXT, model TEXT, input_per_1m_usd REAL,
                cached_input_per_1m_usd REAL, output_per_1m_usd REAL
            );
            CREATE TABLE usage (
                id INTEGER PRIMARY KEY, timestamp TEXT, agent TEXT, backend TEXT,
                model TEXT, project TEXT, input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER, cost_eur REAL, cost_type TEXT, cloud INTEGER
            );
        """)

    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(usage_module, "get_connection", connect)
    result = usage_module.UsageTracker().log_request(
        "chat", backend, "model", "prompt", "response"
    )

    with connect() as conn:
        stored = bool(conn.execute("SELECT cloud FROM usage").fetchone()["cloud"])
    assert result["cloud"] is expected
    assert stored is expected


def test_existing_usage_cloud_flags_are_repaired_without_touching_unknown_backends():
    from services.database import _sync_usage_cloud_flags

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE usage (backend TEXT, cloud INTEGER)")
    conn.executemany(
        "INSERT INTO usage VALUES (?, ?)",
        [("ollama", 1), ("anthropic", 0), ("qwen", 0), ("legacy-provider", 0)],
    )
    _sync_usage_cloud_flags(conn)
    rows = dict(conn.execute("SELECT backend, cloud FROM usage"))
    conn.close()

    assert rows == {
        "ollama": 0,
        "anthropic": 1,
        "qwen": 1,
        "legacy-provider": 0,
    }
