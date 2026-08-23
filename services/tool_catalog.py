"""Canonical product-owned defaults for Sentinel Fork's built-in Chat tools."""

BUILTIN_TOOLS = {
    "General Chat": {
        "description": "Free-form general assistant mode.",
        "system": "You are a helpful general assistant.",
        "recommended_provider": "ollama",
        "recommended_model": "",
    },
    "Writing": {
        "description": "Professional writing, editing, and tone improvement.",
        "system": "You are a professional writing assistant. Improve clarity, tone, structure, grammar, and usefulness while preserving the user's intent.",
        "recommended_provider": "openai",
        "recommended_model": "gpt-4.1-mini",
    },
    "Coding": {
        "description": "Code debugging, refactoring, and explanation.",
        "system": "You are a senior software engineering assistant. Help debug, refactor, explain errors, and produce clean, working code.",
        "recommended_provider": "deepseek",
        "recommended_model": "deepseek-v4-pro",
    },
    "Summarize": {
        "description": "Clear and concise summarization of long texts.",
        "system": "You summarize clearly and concisely. Preserve important facts, names, dates, numbers, decisions, and action items.",
        "recommended_provider": "gemini",
        "recommended_model": "gemini-2.5-flash",
    },
    "Rewrite": {
        "description": "Rewrite text for clarity and professionalism.",
        "system": "You rewrite text clearly, professionally, and naturally while preserving the original meaning.",
        "recommended_provider": "openai",
        "recommended_model": "gpt-4.1-mini",
    },
}

BUILTIN_TOOL_ORDER = tuple(BUILTIN_TOOLS)


def merge_tool_prompts(overrides: dict | None) -> dict:
    """Return ordered built-ins plus custom tools, preserving every override."""
    supplied = overrides if isinstance(overrides, dict) else {}
    merged = {}
    for name, defaults in BUILTIN_TOOLS.items():
        override = supplied.get(name)
        merged[name] = {**defaults, **override} if isinstance(override, dict) else dict(defaults)
    for name, config in supplied.items():
        if name not in merged and isinstance(config, dict):
            merged[name] = dict(config)
    return merged


def runtime_tool_prompts(overrides: dict | None, registry_tools: list[dict]) -> dict:
    """Build the selectable tool map from enabled SQLite registry rows."""
    configured = merge_tool_prompts(overrides)
    enabled = {
        row["name"]: row for row in registry_tools if bool(row.get("enabled", True))
    }
    ordered_names = [name for name in BUILTIN_TOOL_ORDER if name in enabled]
    ordered_names.extend(sorted(name for name in enabled if name not in BUILTIN_TOOLS))

    result = {}
    for name in ordered_names:
        row = enabled[name]
        defaults = configured.get(name, {})
        result[name] = {
            "system": row.get("system_prompt") or defaults.get("system", ""),
            "recommended_provider": (
                row.get("recommended_provider")
                or defaults.get("recommended_provider", "ollama")
            ),
            "recommended_model": (
                row.get("recommended_model")
                or defaults.get("recommended_model", "")
            ),
        }
    return result
