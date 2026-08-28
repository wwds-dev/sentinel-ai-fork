"""Kimi cache-hit usage and billing regression tests."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from services.kimi_client import KimiClientWrapper, cached_input_tokens


class _Completions:
    def __init__(self, response):
        self.response = response

    def create(self, **_kwargs):
        return self.response


def _wrapper(response):
    wrapper = KimiClientWrapper.__new__(KimiClientWrapper)
    wrapper.client = SimpleNamespace(
        chat=SimpleNamespace(completions=_Completions(response))
    )
    return wrapper


def test_kimi_non_stream_usage_captures_documented_cached_tokens():
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        cached_tokens=80,
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
        usage=usage,
    )

    text, normalized = _wrapper(response).chat([], model="kimi-k2.7-code")

    assert text == "done"
    assert normalized == {
        "input_tokens": 100,
        "cached_input_tokens": 80,
        "output_tokens": 20,
        "total_tokens": 120,
    }


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"cached_tokens": 12}, 12),
        ({"cached_input_tokens": "13"}, 13),
        ({"prompt_tokens_details": {"cached_tokens": 14}}, 14),
        ({"input_tokens_details": {"cache_read_input_tokens": 15}}, 15),
        ({"cached_tokens": -5}, 0),
        ({"cached_tokens": "bad"}, 0),
    ],
)
def test_cached_token_parser_accepts_compatible_shapes(usage, expected):
    assert cached_input_tokens(usage) == expected


@pytest.fixture
def tracker_db(tmp_path, monkeypatch):
    from services import usage_tracker as usage_module

    db_path = tmp_path / "usage.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO settings VALUES ('eur_per_usd', '1.0');
            CREATE TABLE pricing (
                backend TEXT, model TEXT, input_per_1m_usd REAL,
                cached_input_per_1m_usd REAL, output_per_1m_usd REAL
            );
            INSERT INTO pricing VALUES ('kimi', 'model', 1.0, 0.2, 4.0);
            CREATE TABLE usage (
                id INTEGER PRIMARY KEY, timestamp TEXT, agent TEXT, backend TEXT,
                model TEXT, project TEXT, input_tokens INTEGER,
                cached_input_tokens INTEGER,
                output_tokens INTEGER, total_tokens INTEGER, cost_eur REAL,
                cost_type TEXT, cloud INTEGER
            );
        """)

    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(usage_module, "get_connection", connect)
    return usage_module.UsageTracker(), connect


def test_actual_cost_splits_cached_and_uncached_input(tracker_db):
    tracker, _connect = tracker_db

    conservative = tracker.calculate_cost_eur("kimi", "model", 1_000_000, 0)
    actual = tracker.calculate_cost_eur(
        "kimi", "model", 1_000_000, 0, cached_input_tokens=800_000
    )

    assert conservative == 1.0
    assert actual == 0.36


def test_log_request_persists_cache_hits_and_actual_cost(tracker_db):
    tracker, connect = tracker_db

    result = tracker.log_request(
        "chat",
        "kimi",
        "model",
        "prompt",
        "response",
        {"input_tokens": 1000, "output_tokens": 100, "cached_tokens": 800},
    )

    assert result["cached_input_tokens"] == 800
    assert result["cost_eur"] == pytest.approx(0.00076)
    with connect() as conn:
        row = conn.execute("SELECT * FROM usage").fetchone()
    assert row["cached_input_tokens"] == 800
    assert row["cost_eur"] == pytest.approx(0.00076)


def test_malformed_or_excess_cache_hits_never_over_discount(tracker_db):
    tracker, _connect = tracker_db

    assert tracker.cached_input_tokens({"cached_tokens": 999}, 100) == 100
    assert tracker.cached_input_tokens({"cached_tokens": "bad"}, 100) == 0
    assert tracker.calculate_cost_eur(
        "kimi", "model", 100, 0, cached_input_tokens=999
    ) == pytest.approx(0.00002)
