"""
profile_store.py — Loads and saves VPN profiles.
Profiles define endpoints, ports, and WireGuard interface names.

The live file lives in the user's application-support directory, not in
config/. This file is written whenever a profile is selected or a built server
is registered, and once the app is frozen the config/ copy sits inside the .app
bundle — writing there breaks the code signature, and a reinstall would discard
every profile the user had. config/vpn_profiles.json is the read-only seed,
copied out on first run.
"""

import json
import os
import shutil

from agents.vpn_agent.server import paths

# Read-only seed shipped with the app.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(_THIS_DIR, "..", "config", "vpn_profiles.json")


def profiles_path() -> str:
    """Path to the writable profile list, seeding it on first use."""
    live = paths.profiles_file()
    if not live.exists():
        paths.ensure_private_dir(live.parent)
        try:
            shutil.copyfile(SEED_PATH, live)
        except OSError:
            # No seed to copy (or it is unreadable) — start from an empty list
            # rather than refusing to run.
            with open(live, "w", encoding="utf-8") as f:
                json.dump({"profiles": [], "active_profile": ""}, f, indent=4)
    return str(live)


# Kept as a module attribute for callers that referenced it directly.
PROFILES_PATH = str(paths.profiles_file())


def _load_raw() -> dict:
    """Load and return the raw JSON config dict."""
    with open(profiles_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: dict) -> None:
    """Write a dict back to the profiles JSON file."""
    with open(profiles_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_profiles() -> list[dict]:
    """Return all VPN profiles as a list of dicts."""
    try:
        return _load_raw().get("profiles", [])
    except Exception as e:
        print(f"[profile_store] Failed to load profiles: {e}")
        return []


def get_profile_names() -> list[str]:
    """Return just the name strings — useful for populating a dropdown."""
    return [p.get("name", "Unnamed") for p in get_profiles()]


def get_active_profile_name() -> str | None:
    """Return the name of the currently selected active profile, or None."""
    try:
        return _load_raw().get("active_profile", None)
    except Exception:
        return None


def set_active_profile(name: str) -> None:
    """Set a profile as active by name and persist to disk."""
    try:
        data = _load_raw()
        data["active_profile"] = name
        _save_raw(data)
    except Exception as e:
        print(f"[profile_store] Failed to set active profile: {e}")


def get_profile_by_name(name: str) -> dict | None:
    """Return the profile dict matching the given name, or None if not found."""
    for profile in get_profiles():
        if profile.get("name") == name:
            return profile
    return None


def add_profile(profile: dict) -> None:
    """Add a new profile dict and save. Does not check for duplicates."""
    try:
        data = _load_raw()
        data["profiles"].append(profile)
        _save_raw(data)
    except Exception as e:
        print(f"[profile_store] Failed to add profile: {e}")


def remove_profile(name: str) -> bool:
    """Remove a profile by name. Returns True if removed, False if not found."""
    try:
        data = _load_raw()
        original = data["profiles"]
        data["profiles"] = [p for p in original if p.get("name") != name]
        if len(data["profiles"]) < len(original):
            _save_raw(data)
            return True
        return False
    except Exception as e:
        print(f"[profile_store] Failed to remove profile: {e}")
        return False
