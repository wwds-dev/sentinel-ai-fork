import json

from services import database
from services.history_store import HistoryStore
from services.registry import Registry


def test_project_registry_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "sentinel.db")
    database.init_db()
    registry = Registry()

    saved = registry.upsert_project({
        "name": "Moonlight Novel",
        "instructions": "Use Irish English and preserve the cast bible.",
        "default_agent": "writing",
        "default_provider": "anthropic",
        "default_model": "claude-sonnet-5",
        "budget_eur": 2.5,
    })

    assert saved["id"] == "moonlight-novel"
    assert registry.get_project(saved["id"])["instructions"].startswith("Use Irish")
    assert registry.list_projects()[0]["budget_eur"] == 2.5

    registry.archive_project(saved["id"])
    assert registry.list_projects() == []
    assert registry.list_projects(include_archived=True)[0]["archived"] == 1


def test_history_project_is_optional_and_assignable(tmp_path):
    store = HistoryStore(str(tmp_path))
    store.save_chat("chat", "ollama", "local", "General Chat", [], "hello")
    path = store.list_chats()[0]
    assert store.load_chat(str(path)).get("project") is None

    store.assign_project(str(path), "moonlight-novel")
    assert store.load_chat(str(path))["project"] == "moonlight-novel"
    store.assign_project(str(path), None)
    assert "project" not in store.load_chat(str(path))


def test_legacy_chat_without_project_still_loads(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"agent": "chat", "response": "old"}), encoding="utf-8")
    assert HistoryStore(str(tmp_path)).load_chat(str(path))["response"] == "old"
