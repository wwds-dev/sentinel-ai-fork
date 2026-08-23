"""Canonical built-in tool defaults and non-destructive reconciliation."""

import sqlite3


def test_prompt_merge_restores_missing_builtins_and_preserves_customizations():
    from services.tool_catalog import BUILTIN_TOOL_ORDER, merge_tool_prompts

    merged = merge_tool_prompts({
        "Writing": {"system": "My private writing instructions."},
        "My Tool": {"system": "Custom tool."},
    })

    assert tuple(merged)[:len(BUILTIN_TOOL_ORDER)] == BUILTIN_TOOL_ORDER
    assert merged["Writing"]["system"] == "My private writing instructions."
    assert merged["Writing"]["recommended_provider"] == "openai"
    assert merged["My Tool"]["system"] == "Custom tool."


def test_database_reconciliation_preserves_policy_and_custom_tools(tmp_path, monkeypatch):
    from services import database
    from services.tool_catalog import BUILTIN_TOOLS

    db_path = tmp_path / "data" / "sentinel.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    monkeypatch.setattr(database, "BASE_DIR", tmp_path)
    database.init_db()

    with database.get_connection() as conn:
        conn.execute("DELETE FROM tools WHERE name = 'Summarize'")
        conn.execute(
            """UPDATE tools SET enabled=0, allowed_providers='[\"ollama\"]',
               budget_limit_eur=2.5, requires_approval=1, system_prompt='mine'
               WHERE name='Writing'"""
        )
        conn.execute(
            "INSERT INTO tools (name, label, system_prompt) VALUES ('My Tool', 'My Tool', 'custom')"
        )
        conn.commit()

    database.init_db()
    with database.get_connection() as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM tools")}
        writing = conn.execute(
            """SELECT enabled, allowed_providers, budget_limit_eur,
                      requires_approval, system_prompt FROM tools WHERE name='Writing'"""
        ).fetchone()

    assert set(BUILTIN_TOOLS) <= names
    assert "My Tool" in names
    assert tuple(writing) == (0, '["ollama"]', 2.5, 1, "mine")


def test_runtime_selector_matches_enabled_registry_and_keeps_catalog_order():
    from services.tool_catalog import runtime_tool_prompts

    tools = runtime_tool_prompts(
        {"Writing": {"system": "edited"}},
        [
            {"name": "My Tool", "enabled": 1, "system_prompt": "custom"},
            {"name": "Coding", "enabled": 0},
            {"name": "Writing", "enabled": 1, "system_prompt": "database override"},
            {"name": "General Chat", "enabled": 1},
        ],
    )

    assert tuple(tools) == ("General Chat", "Writing", "My Tool")
    assert tools["Writing"]["system"] == "database override"
    assert tools["My Tool"]["system"] == "custom"
