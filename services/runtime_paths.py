"""Central path resolution for Sentinel Fork.

In development (running `python main.py`) every path resolves to the project
root exactly as before — behaviour is unchanged.

When frozen by PyInstaller (`sys.frozen` is set) the app bundle is read-only,
so writable state (SQLite DB, saved chats, logs, editable config, .env) is
redirected to  ~/Library/Application Support/Sentinel Fork/  and seeded from the
read-only copies bundled inside the .app on first launch.

Both main.py and services/database.py import from here so they always agree on
where the writable data lives.
"""
import sys
import shutil
from pathlib import Path

APP_NAME = "Sentinel Fork"
LEGACY_APP_NAMES = ("Sentinel", "Sentinel AI")


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def resource_base() -> Path:
    """Read-only bundled resources (README.md, config defaults, assets).

    Frozen: PyInstaller extracts datas next to the executable and exposes the
    root via sys._MEIPASS. Dev: the project root.
    """
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_base() -> Path:
    """Writable base directory.

    Frozen: ~/Library/Application Support/Sentinel Fork  (created if missing).
    Dev:    the project root, so `python main.py` keeps writing in-place.
    """
    if is_frozen():
        d = Path.home() / "Library" / "Application Support" / APP_NAME
        if not d.exists():
            for legacy_name in LEGACY_APP_NAMES:
                legacy = d.parent / legacy_name
                if legacy.exists():
                    # Copy, rather than move: the fork and original stay independent.
                    shutil.copytree(legacy, d)
                    break
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent.parent


def ensure_seeded() -> None:
    """On first frozen launch, copy the bundled read-only defaults into the
    writable user-data directory so the rest of the app can read AND write them.
    No-op in development."""
    if not is_frozen():
        return

    ub = user_data_base()
    rb = resource_base()

    # Seed editable config/ (settings.json is written at runtime).
    dst_config = ub / "config"
    if not dst_config.exists():
        src_config = rb / "config"
        if src_config.exists():
            shutil.copytree(src_config, dst_config)
        else:
            dst_config.mkdir(parents=True, exist_ok=True)

    # Ensure writable data directories exist.
    (ub / "data").mkdir(exist_ok=True)
    (ub / "data" / "chats").mkdir(exist_ok=True)
    (ub / "data" / "logs").mkdir(exist_ok=True)

    # Seed a .env template so the user has one place to paste API keys.
    env_file = ub / ".env"
    if not env_file.exists():
        example = rb / ".env.example"
        if example.exists():
            shutil.copy(example, env_file)
        else:
            env_file.write_text(
                "OPENAI_API_KEY=\n"
                "DEEPSEEK_API_KEY=\n"
                "KIMI_API_KEY=\n"
                "GOOGLE_API_KEY=\n"
                "ANTHROPIC_API_KEY=\n",
                encoding="utf-8",
            )
