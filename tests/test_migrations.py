"""Upgrade-safety tests for persistent database and frozen config data."""

import sqlite3

import pytest


def test_preversioned_database_is_upgraded_without_losing_user_data(tmp_path, monkeypatch):
    from services import database

    db_path = tmp_path / "data" / "sentinel.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE agents (name TEXT PRIMARY KEY, label TEXT NOT NULL DEFAULT '');
        CREATE TABLE usage (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, agent TEXT NOT NULL DEFAULT '',
            backend TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
            input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0, cost_eur REAL NOT NULL DEFAULT 0.0
        );
        INSERT INTO agents (name, label) VALUES ('my_agent', 'My Agent');
        INSERT INTO usage (timestamp, agent, backend) VALUES ('2026-01-01', 'my_agent', 'qwen');
        CREATE TABLE legacy_notes (body TEXT NOT NULL);
        INSERT INTO legacy_notes VALUES ('keep me');
    """)
    conn.close()

    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "BASE_DIR", tmp_path)
    database.init_db()

    backups = list(
        (db_path.parent / "backups").glob(
            f"sentinel.v0.before-v{database.SCHEMA_VERSION}.*.db"
        )
    )
    assert len(backups) == 1
    backup = sqlite3.connect(backups[0])
    assert backup.execute("SELECT label FROM agents WHERE name='my_agent'").fetchone()[0] == "My Agent"
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 0
    backup.close()

    conn = database.get_connection()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    assert conn.execute("SELECT label FROM agents WHERE name='my_agent'").fetchone()[0] == "My Agent"
    assert conn.execute("SELECT cloud FROM usage WHERE agent='my_agent'").fetchone()[0] == 1
    assert conn.execute("SELECT body FROM legacy_notes").fetchone()[0] == "keep me"
    usage_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(usage)").fetchall()
    }
    pricing_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(pricing)").fetchall()
    }
    assert "cached_input_tokens" in usage_columns
    assert "cached_input_per_1m_usd" in pricing_columns
    conn.close()


def test_database_migration_is_idempotent(tmp_path, monkeypatch):
    from services import database

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "data" / "sentinel.db")
    monkeypatch.setattr(database, "BASE_DIR", tmp_path)
    database.init_db()
    database.init_db()

    conn = database.get_connection()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION
    conn.close()
    assert not (database.DB_PATH.parent / "backups").exists()


def test_v1_database_adds_kimi_cache_columns_and_rates(tmp_path, monkeypatch):
    from services import database

    db_path = tmp_path / "data" / "sentinel.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        PRAGMA user_version = 1;
        CREATE TABLE usage (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL,
            input_tokens INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO usage (timestamp, input_tokens) VALUES ('keep', 42);
        CREATE TABLE pricing (
            backend TEXT NOT NULL, model TEXT NOT NULL,
            input_per_1m_usd REAL NOT NULL DEFAULT 0.0,
            output_per_1m_usd REAL NOT NULL DEFAULT 0.0,
            PRIMARY KEY (backend, model)
        );
        INSERT INTO pricing VALUES ('kimi', 'kimi-k2.7-code', 0.95, 4.0);
    """)
    conn.close()

    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "BASE_DIR", tmp_path)
    database.init_db()

    with database.get_connection() as conn:
        assert (
            conn.execute("PRAGMA user_version").fetchone()[0]
            == database.SCHEMA_VERSION
        )
        usage = conn.execute(
            "SELECT input_tokens, cached_input_tokens FROM usage WHERE timestamp='keep'"
        ).fetchone()
        pricing = conn.execute(
            "SELECT cached_input_per_1m_usd FROM pricing "
            "WHERE backend='kimi' AND model='kimi-k2.7-code'"
        ).fetchone()
    assert tuple(usage) == (42, 0)
    assert pricing[0] == pytest.approx(0.19)


def test_newer_database_is_rejected_without_downgrade(tmp_path, monkeypatch):
    from services import database

    db_path = tmp_path / "sentinel.db"
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {database.SCHEMA_VERSION + 1}")
    conn.execute("CREATE TABLE future_data (value TEXT)")
    conn.execute("INSERT INTO future_data VALUES ('preserve')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(database, "DB_PATH", db_path)

    with pytest.raises(RuntimeError, match="newer than"):
        database.init_db()

    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM future_data").fetchone()[0] == "preserve"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == database.SCHEMA_VERSION + 1
    conn.close()


def test_frozen_config_seeding_adds_missing_files_without_overwriting(tmp_path, monkeypatch):
    from services import runtime_paths

    resources = tmp_path / "bundle"
    user_data = tmp_path / "user"
    (resources / "config").mkdir(parents=True)
    (resources / "config" / "settings.json").write_text('{"theme":"default"}')
    (resources / "config" / "new_defaults.json").write_text('{"added":true}')
    (user_data / "config").mkdir(parents=True)
    (user_data / "config" / "settings.json").write_text('{"theme":"mine"}')

    monkeypatch.setattr(runtime_paths, "is_frozen", lambda: True)
    monkeypatch.setattr(runtime_paths, "resource_base", lambda: resources)
    monkeypatch.setattr(runtime_paths, "user_data_base", lambda: user_data)
    runtime_paths.ensure_seeded()

    assert (user_data / "config" / "settings.json").read_text() == '{"theme":"mine"}'
    assert (user_data / "config" / "new_defaults.json").read_text() == '{"added":true}'


def test_saved_database_budget_takes_precedence_over_json(monkeypatch):
    import main

    monkeypatch.setattr(main, "get_setting", lambda key, fallback: "12.5")
    assert main.load_budget_setting({"session_budget_eur": 2.0}, "session_budget_eur", 1.0) == 12.5
