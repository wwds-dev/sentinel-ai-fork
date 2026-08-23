"""Input-boundary tests for Forge agent specifications."""

from __future__ import annotations

import copy
import sqlite3

import pytest

from services import agent_factory as agent_factory_module
from services.agent_factory import AgentFactory
from services.provider_catalog import SUPPORTED_PROVIDERS


VALID_SPEC = {
    "name": "weather_brief",
    "label": "Weather Brief",
    "description": "Produces a compact weather brief.",
    "allowed_providers": ["ollama", "openai"],
    "allowed_tools": ["General Chat", "Summarize"],
    "budget_limit_eur": 1.5,
    "requires_approval": True,
    "system_prompt": "Write a compact, sourced weather brief.",
}

KNOWN_TOOLS = ("General Chat", "Writing", "Coding", "Summarize", "Rewrite")


@pytest.fixture
def factory(tmp_path, monkeypatch):
    (tmp_path / "agents").mkdir()
    db_path = tmp_path / "registry.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE agents (name TEXT PRIMARY KEY, label TEXT)")
        conn.execute("CREATE TABLE tools (name TEXT PRIMARY KEY, label TEXT)")
        conn.executemany(
            "INSERT INTO tools (name, label) VALUES (?, ?)",
            [(name, name) for name in KNOWN_TOOLS],
        )

    def connect():
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(agent_factory_module, "get_connection", connect)
    return AgentFactory(tmp_path)


def _validate(factory, **changes):
    spec = copy.deepcopy(VALID_SPEC)
    spec.update(changes)
    return factory.validate_spec(spec)


def test_well_formed_spec_is_accepted(factory):
    assert _validate(factory) == (True, "OK")


def test_manager_prompt_advertises_every_supported_provider():
    from agents.manager_agent import MANAGER_SYSTEM_PROMPT

    for provider in SUPPORTED_PROVIDERS:
        assert f'"{provider}"' in MANAGER_SYSTEM_PROMPT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", 12),
        ("label", None),
        ("description", ["not", "text"]),
        ("allowed_providers", "ollama"),
        ("allowed_providers", ["ollama", 12]),
        ("allowed_tools", "General Chat"),
        ("allowed_tools", ["General Chat", 12]),
        ("budget_limit_eur", "1.50"),
        ("budget_limit_eur", True),
        ("requires_approval", 1),
        ("requires_approval", "yes"),
        ("system_prompt", ["not", "text"]),
    ],
)
def test_field_types_are_strictly_validated(factory, field, value):
    valid, message = _validate(factory, **{field: value})
    assert valid is False
    assert message


@pytest.mark.parametrize("spec", [None, [], "agent", 42])
def test_non_mapping_specs_are_rejected_without_raising(factory, spec):
    valid, message = factory.validate_spec(spec)
    assert valid is False
    assert "spec" in message.lower()


@pytest.mark.parametrize("provider", ["unknown", "OpenAI", "", " openai"])
def test_unknown_or_noncanonical_providers_are_rejected(factory, provider):
    valid, message = _validate(factory, allowed_providers=[provider])
    assert valid is False
    assert "provider" in message.lower()


@pytest.mark.parametrize("tool", ["Web Search", "general chat", "", " Summarize"])
def test_unknown_or_noncanonical_tool_names_are_rejected(factory, tool):
    valid, message = _validate(factory, allowed_tools=[tool])
    assert valid is False
    assert "tool" in message.lower()


@pytest.mark.parametrize("budget", [-0.01, float("nan"), float("inf"), -float("inf")])
def test_budget_must_be_finite_and_nonnegative(factory, budget):
    valid, message = _validate(factory, budget_limit_eur=budget)
    assert valid is False
    assert "budget_limit_eur" in message


def test_unlimited_budget_is_allowed(factory):
    assert _validate(factory, budget_limit_eur=None)[0] is True


@pytest.mark.parametrize("field", ["label", "description", "system_prompt"])
@pytest.mark.parametrize("value", ["", "   ", "\n\t"])
def test_user_facing_text_fields_must_not_be_blank(factory, field, value):
    valid, message = _validate(factory, **{field: value})
    assert valid is False
    assert field in message


@pytest.mark.parametrize("label", ["General Chat", "general chat", " Summarize "])
def test_agent_label_cannot_collide_with_an_existing_tool(factory, label):
    valid, message = _validate(factory, label=label)
    assert valid is False
    assert "tool" in message.lower()
