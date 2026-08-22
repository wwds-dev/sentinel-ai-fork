import json
import sqlite3
from pathlib import Path

from services.runtime_paths import user_data_base

# Writable base: project root in dev, ~/Library/Application Support/Sentinel when frozen.
BASE_DIR = user_data_base()
DB_PATH = BASE_DIR / "data" / "sentinel.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    name                TEXT PRIMARY KEY,
    label               TEXT NOT NULL DEFAULT '',
    enabled             INTEGER NOT NULL DEFAULT 1,
    version             TEXT NOT NULL DEFAULT '1.0',
    allowed_providers   TEXT NOT NULL DEFAULT '[]',
    allowed_tools       TEXT,
    budget_limit_eur    REAL,
    requires_approval   INTEGER NOT NULL DEFAULT 0,
    description         TEXT NOT NULL DEFAULT '',
    log_path            TEXT NOT NULL DEFAULT 'data/logs/runs.jsonl',
    auto_generated      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tools (
    name                 TEXT PRIMARY KEY,
    label                TEXT NOT NULL DEFAULT '',
    enabled              INTEGER NOT NULL DEFAULT 1,
    version              TEXT NOT NULL DEFAULT '1.0',
    allowed_providers    TEXT NOT NULL DEFAULT '[]',
    budget_limit_eur     REAL,
    requires_approval    INTEGER NOT NULL DEFAULT 0,
    description          TEXT NOT NULL DEFAULT '',
    system_prompt        TEXT NOT NULL DEFAULT '',
    recommended_provider TEXT NOT NULL DEFAULT 'ollama',
    recommended_model    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS usage (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,
    agent         TEXT NOT NULL DEFAULT '',
    backend       TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_eur      REAL NOT NULL DEFAULT 0.0,
    cost_type     TEXT NOT NULL DEFAULT 'estimated',
    cloud         INTEGER NOT NULL DEFAULT 0
    ,project       TEXT
);

CREATE TABLE IF NOT EXISTS projects (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    instructions     TEXT NOT NULL DEFAULT '',
    default_agent    TEXT NOT NULL DEFAULT 'chat',
    default_provider TEXT NOT NULL DEFAULT '',
    default_model    TEXT NOT NULL DEFAULT '',
    budget_eur       REAL,
    archived         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         TEXT NOT NULL UNIQUE,
    timestamp      TEXT NOT NULL,
    agent          TEXT NOT NULL DEFAULT '',
    tool           TEXT NOT NULL DEFAULT '',
    provider       TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    mode           TEXT NOT NULL DEFAULT '',
    prompt_summary TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'running',
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_eur       REAL NOT NULL DEFAULT 0.0,
    duration_sec   REAL NOT NULL DEFAULT 0.0,
    error          TEXT
);

CREATE TABLE IF NOT EXISTS pricing (
    backend          TEXT NOT NULL,
    model            TEXT NOT NULL,
    input_per_1m_usd REAL NOT NULL DEFAULT 0.0,
    cached_input_per_1m_usd REAL,
    output_per_1m_usd REAL NOT NULL DEFAULT 0.0,
    price_source      TEXT,
    verified_at       TEXT,
    price_region      TEXT,
    price_tier        TEXT,
    price_status      TEXT NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (backend, model)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manuscript_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at    TEXT NOT NULL,
    source        TEXT NOT NULL,
    period_from   TEXT,
    period_to     TEXT,
    total_units   INTEGER NOT NULL DEFAULT 0,
    total_revenue REAL    NOT NULL DEFAULT 0.0,
    currency      TEXT    NOT NULL DEFAULT 'USD',
    raw_json      TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS manuscript_kdp_ingested (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    filename            TEXT NOT NULL UNIQUE,
    ingested_at         TEXT NOT NULL,
    total_units         INTEGER NOT NULL DEFAULT 0,
    total_royalties_usd REAL    NOT NULL DEFAULT 0.0,
    kenp_pages_read     INTEGER NOT NULL DEFAULT 0,
    raw_summary_json    TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS manuscript_todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    title       TEXT NOT NULL,
    platform    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    priority    TEXT NOT NULL DEFAULT 'normal',
    due_date    TEXT,
    notes       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_runs_timestamp  ON runs(timestamp);
CREATE INDEX IF NOT EXISTS idx_runs_run_id     ON runs(run_id);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def save_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
            (key, value)
        )
        conn.commit()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not DB_PATH.exists()
    conn = get_connection()
    conn.executescript(SCHEMA)
    _ensure_schema_columns(conn)
    conn.commit()
    if is_new:
        _migrate_from_json(conn)
    _seed_missing_pricing(conn)
    _sync_cached_pricing(conn)
    _sync_pricing_metadata(conn)
    _correct_stale_pricing(conn)
    _seed_default_agents(conn)
    _sync_agent_labels(conn)
    conn.close()


def _ensure_schema_columns(conn: sqlite3.Connection) -> None:
    pricing_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(pricing)")
    }
    if "cached_input_per_1m_usd" not in pricing_columns:
        conn.execute("ALTER TABLE pricing ADD COLUMN cached_input_per_1m_usd REAL")
    for name, declaration in {
        "price_source": "TEXT", "verified_at": "TEXT", "price_region": "TEXT",
        "price_tier": "TEXT", "price_status": "TEXT NOT NULL DEFAULT 'unknown'",
    }.items():
        if name not in pricing_columns:
            conn.execute(f"ALTER TABLE pricing ADD COLUMN {name} {declaration}")
    usage_columns = {row["name"] for row in conn.execute("PRAGMA table_info(usage)")}
    if "project" not in usage_columns:
        conn.execute("ALTER TABLE usage ADD COLUMN project TEXT")
    conn.commit()


def _sync_cached_pricing(conn: sqlite3.Connection) -> None:
    """Load cache-read rates and seed their rows without overwriting user prices."""
    data = _load_json(BASE_DIR / "config" / "pricing.json", {})
    for backend, models in data.items():
        if not isinstance(models, dict):
            continue
        for model, prices in models.items():
            if not isinstance(prices, dict):
                continue
            cached = prices.get("cached_input_per_1m_usd")
            if cached is not None:
                conn.execute(
                    """INSERT INTO pricing
                       (backend, model, input_per_1m_usd,
                        cached_input_per_1m_usd, output_per_1m_usd)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(backend, model) DO UPDATE SET
                         cached_input_per_1m_usd = excluded.cached_input_per_1m_usd""",
                    (
                        backend,
                        model,
                        float(prices.get("input_per_1m_usd", 0.0)),
                        float(cached),
                        float(prices.get("output_per_1m_usd", 0.0)),
                    ),
                )
    conn.commit()


def _sync_pricing_metadata(conn: sqlite3.Connection) -> None:
    """Refresh catalogue provenance without overwriting user-edited rates."""
    data = _load_json(BASE_DIR / "config" / "pricing.json", {})
    fx = data.get("fx", {})
    catalog = data.get("catalog", {})
    if isinstance(fx, dict):
        for key in ("source", "verified_at", "status"):
            if fx.get(key) is not None:
                conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                             (f"eur_per_usd_{key}", str(fx[key])))
    for backend, models in data.items():
        if backend in {"eur_per_usd", "fx", "catalog"} or not isinstance(models, dict):
            continue
        for model, prices in models.items():
            if not isinstance(prices, dict):
                continue
            conn.execute(
                """UPDATE pricing SET price_source=?, verified_at=?, price_region=?,
                   price_tier=?, price_status=? WHERE backend=? AND model=?""",
                (prices.get("source", catalog.get("source")),
                 prices.get("verified_at", catalog.get("verified_at")), prices.get("region"),
                 prices.get("tier", catalog.get("tier")),
                 prices.get("status", catalog.get("status", "unknown")), backend, model),
            )
    conn.commit()


def _sync_agent_labels(conn: sqlite3.Connection) -> None:
    """Ensure built-in agents' DB labels match the current brand names shown in the GUI."""
    rename_map = {
        "chat":        "Chat",
        "osint":       "Trace",
        "osint_heavy": "Bloodhound",
        "wifi":        "Beacon",
        "bug_bounty":  "Bug Spray",
        "manager":     "Forge",
    }
    for name, label in rename_map.items():
        conn.execute("UPDATE agents SET label = ? WHERE name = ?", (label, name))
    conn.commit()


def _correct_stale_pricing(conn: sqlite3.Connection) -> None:
    """One-time repair of pricing rows that were seeded at the wrong rate.

    _seed_missing_pricing uses INSERT OR IGNORE, so it can add new models but
    never fixes a row that already exists. These three were wrong: the Opus
    4.6/4.7 rows carried the old Opus 4.1 rate of 15/75 when those models
    actually bill at 5/25, and Haiku 4.5 was seeded a notch low.

    Guarded by a settings flag so it runs once and never overwrites a price the
    user has since edited in Settings -> Pricing.
    """
    flag = conn.execute(
        "SELECT value FROM settings WHERE key = 'pricing_correction_2026_08'"
    ).fetchone()
    if flag:
        return

    corrections = [
        ("anthropic", "claude-opus-4-6",            5.00, 25.00, 15.00, 75.00),
        ("anthropic", "claude-opus-4-7",            5.00, 25.00, 15.00, 75.00),
        ("anthropic", "claude-haiku-4-5-20251001",  1.00,  5.00,  0.80,  4.00),
    ]
    for backend, model, new_in, new_out, old_in, old_out in corrections:
        # Only touch rows still holding the original wrong value.
        conn.execute(
            "UPDATE pricing SET input_per_1m_usd = ?, output_per_1m_usd = ? "
            "WHERE backend = ? AND model = ? "
            "AND input_per_1m_usd = ? AND output_per_1m_usd = ?",
            (new_in, new_out, backend, model, old_in, old_out),
        )

    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('pricing_correction_2026_08', 'done')"
    )
    conn.commit()


def _seed_missing_pricing(conn: sqlite3.Connection) -> None:
    """Insert default pricing rows that may not exist yet (e.g. new providers)."""
    # Anthropic list prices per 1M tokens, from the official pricing table.
    # Note the Opus 4.5-and-later tier is 5/25, NOT the 15/75 that Opus 4/4.1
    # charged — seeding those at 15/75 overstated every estimate threefold.
    defaults = [
        ("anthropic", "claude-fable-5",            10.00,  50.00),
        ("anthropic", "claude-opus-5",              5.00,  25.00),
        ("anthropic", "claude-sonnet-5",            2.00,  10.00),
        ("anthropic", "claude-opus-4-8",            5.00,  25.00),
        ("anthropic", "claude-opus-4-7",            5.00,  25.00),
        ("anthropic", "claude-opus-4-6",            5.00,  25.00),
        ("anthropic", "claude-opus-4-5-20251101",   5.00,  25.00),
        ("anthropic", "claude-opus-4-1-20250805",  15.00,  75.00),
        ("anthropic", "claude-sonnet-4-6",          3.00,  15.00),
        ("anthropic", "claude-sonnet-4-5-20250929", 3.00,  15.00),
        ("anthropic", "claude-haiku-4-5-20251001",  1.00,   5.00),
        ("anthropic", "claude-3-5-sonnet-20241022", 3.00,  15.00),
        ("anthropic", "claude-3-5-haiku-20241022",  0.80,   4.00),
        ("anthropic", "claude-3-opus-20240229",    15.00,  75.00),
        ("anthropic", "claude-3-haiku-20240307",    0.25,   1.25),
        ("anthropic", "default",                    3.00,  15.00),
        # Qwen via Alibaba Model Studio. Pricing is regional — these are the
        # Frankfurt/EU rates (Singapore is dearer at 2.00 / 6.00).
        ("qwen", "qwen3.8-max",                     1.65,   4.951),
        ("qwen", "qwen3-max",                       1.65,   4.951),
        ("qwen", "default",                         1.65,   4.951),
    ]
    for backend, model, inp, out in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO pricing (backend, model, input_per_1m_usd, output_per_1m_usd) VALUES (?,?,?,?)",
            (backend, model, inp, out),
        )
    conn.commit()


def _seed_default_agents(conn: sqlite3.Connection) -> None:
    """Insert built-in agents that may not exist in the DB yet (new agents added in updates)."""
    # Quick ROI and Oracle (investment) are deliberately absent: that work moved
    # to the SONAR app, and their panels and agent modules were removed here.
    # Re-adding them would resurrect orphaned registry rows on every launch.
    agents = [
        {
            "name": "wifi",
            "label": "Wi-Fi Adapter",
            "description": "Wi-Fi diagnostics, network scanning, signal monitoring, and Kali Linux aircrack-ng command generation for authorised wireless testing.",
            "allowed_providers": json.dumps([]),
            "allowed_tools": None,
            "budget_limit_eur": None,
            "requires_approval": 0,
            "log_path": "data/logs/runs.jsonl",
            "auto_generated": 0,
        },
        {
            "name": "osint_heavy",
            "label": "OSINT Pro",
            "description": "Deep structured investigation dossier — entity profiling, digital footprint, infrastructure mapping, breach exposure, and curated tool methodology.",
            "allowed_providers": json.dumps([]),
            "allowed_tools": None,
            "budget_limit_eur": None,
            "requires_approval": 0,
            "log_path": "data/logs/runs.jsonl",
            "auto_generated": 0,
        },
        {
            "name": "bug_bounty",
            "label": "Bug Bounty",
            "description": "Vulnerability research, code review, nmap recon, Burp Suite analysis, and professional bug bounty report generation for authorized programs.",
            "allowed_providers": json.dumps([]),
            "allowed_tools": None,
            "budget_limit_eur": None,
            "requires_approval": 0,
            "log_path": "data/logs/runs.jsonl",
            "auto_generated": 0,
        },
        {
            "name": "vpn",
            "label": "VPN Tunnel",
            "description": "Self-hosted VPN design and troubleshooting — WireGuard + OpenVPN TCP/443 fallback, remote vs native topology, fail-closed kill switch, DNS/IPv6 leak checks, plus an offline WireGuard config and deploy-runbook builder.",
            "allowed_providers": json.dumps([]),
            "allowed_tools": None,
            "budget_limit_eur": None,
            "requires_approval": 0,
            "log_path": "data/logs/runs.jsonl",
            "auto_generated": 0,
        },
    ]
    for a in agents:
        conn.execute("""
            INSERT OR IGNORE INTO agents
              (name, label, enabled, version, allowed_providers, allowed_tools,
               budget_limit_eur, requires_approval, description, log_path, auto_generated)
            VALUES (?,?,1,'1.0',?,?,?,?,?,?,?)
        """, (
            a["name"], a["label"],
            a["allowed_providers"], a["allowed_tools"],
            a["budget_limit_eur"], a["requires_approval"],
            a["description"], a["log_path"], a["auto_generated"],
        ))
    conn.commit()


# ──────────────────────────────────────────────────────────────
# Migration
# ──────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _migrate_from_json(conn: sqlite3.Connection) -> None:
    print("[DB] First run — migrating JSON files to SQLite...")

    _migrate_registry(conn)
    _migrate_tool_prompts(conn)
    _migrate_pricing(conn)
    _migrate_usage_log(conn)
    _migrate_runs(conn)
    _migrate_settings(conn)

    conn.commit()
    print("[DB] Migration complete.")


def _migrate_registry(conn: sqlite3.Connection) -> None:
    path = BASE_DIR / "config" / "registry.json"
    data = _load_json(path, {"agents": [], "tools": []})

    for a in data.get("agents", []):
        conn.execute("""
            INSERT OR IGNORE INTO agents
              (name, label, enabled, version, allowed_providers, allowed_tools,
               budget_limit_eur, requires_approval, description, log_path, auto_generated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            a.get("name", ""),
            a.get("label", ""),
            1 if a.get("enabled", True) else 0,
            a.get("version", "1.0"),
            json.dumps(a.get("allowed_providers", [])),
            json.dumps(a.get("allowed_tools")) if a.get("allowed_tools") is not None else None,
            a.get("budget_limit_eur"),
            1 if a.get("requires_approval", False) else 0,
            a.get("description", ""),
            a.get("log_path", "data/logs/runs.jsonl"),
            1 if a.get("auto_generated", False) else 0,
        ))

    for t in data.get("tools", []):
        conn.execute("""
            INSERT OR IGNORE INTO tools
              (name, label, enabled, version, allowed_providers,
               budget_limit_eur, requires_approval, description)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            t.get("name", ""),
            t.get("name", ""),
            1 if t.get("enabled", True) else 0,
            t.get("version", "1.0"),
            json.dumps(t.get("allowed_providers", [])),
            t.get("budget_limit_eur"),
            1 if t.get("requires_approval", False) else 0,
            t.get("description", ""),
        ))


def _migrate_tool_prompts(conn: sqlite3.Connection) -> None:
    path = BASE_DIR / "config" / "tool_prompts.json"
    data = _load_json(path, {})

    for name, cfg in data.items():
        conn.execute("""
            INSERT INTO tools (name, label, system_prompt, recommended_provider, recommended_model)
            VALUES (?,?,?,?,?)
            ON CONFLICT(name) DO UPDATE SET
              system_prompt        = excluded.system_prompt,
              recommended_provider = excluded.recommended_provider,
              recommended_model    = excluded.recommended_model
        """, (
            name,
            name,
            cfg.get("system", ""),
            cfg.get("recommended_provider", "ollama"),
            cfg.get("recommended_model", ""),
        ))


def _migrate_pricing(conn: sqlite3.Connection) -> None:
    path = BASE_DIR / "config" / "pricing.json"
    data = _load_json(path, {})

    eur_per_usd = data.get("eur_per_usd", 0.92)
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("eur_per_usd", str(eur_per_usd))
    )

    for backend, models in data.items():
        if backend == "eur_per_usd" or not isinstance(models, dict):
            continue
        for model, prices in models.items():
            if not isinstance(prices, dict):
                continue
            conn.execute("""
                INSERT OR REPLACE INTO pricing
                  (backend, model, input_per_1m_usd, cached_input_per_1m_usd,
                   output_per_1m_usd)
                VALUES (?,?,?,?,?)
            """, (
                backend,
                model,
                float(prices.get("input_per_1m_usd", 0.0)),
                (float(prices["cached_input_per_1m_usd"])
                 if prices.get("cached_input_per_1m_usd") is not None else None),
                float(prices.get("output_per_1m_usd", 0.0)),
            ))


def _migrate_usage_log(conn: sqlite3.Connection) -> None:
    path = BASE_DIR / "data" / "usage_log.json"
    entries = _load_json(path, [])

    for e in entries:
        conn.execute("""
            INSERT INTO usage
              (timestamp, agent, backend, model, input_tokens, output_tokens,
               total_tokens, cost_eur, cost_type, cloud)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            e.get("timestamp", ""),
            e.get("agent", ""),
            e.get("backend", ""),
            e.get("model", ""),
            int(e.get("input_tokens", 0)),
            int(e.get("output_tokens", 0)),
            int(e.get("total_tokens", 0)),
            float(e.get("cost_eur", e.get("estimated_cost", 0.0))),
            e.get("cost_type", "estimated"),
            1 if e.get("cloud", False) else 0,
        ))


def _migrate_runs(conn: sqlite3.Connection) -> None:
    path = BASE_DIR / "data" / "logs" / "runs.jsonl"
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            conn.execute("""
                INSERT OR IGNORE INTO runs
                  (run_id, timestamp, agent, tool, provider, model, mode,
                   prompt_summary, status, input_tokens, output_tokens,
                   cost_eur, duration_sec, error)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                e.get("run_id", ""),
                e.get("timestamp", ""),
                e.get("agent", ""),
                e.get("tool", ""),
                e.get("provider", ""),
                e.get("model", ""),
                e.get("mode", ""),
                e.get("prompt_summary", ""),
                e.get("status", "success"),
                int(e.get("input_tokens", 0)),
                int(e.get("output_tokens", 0)),
                float(e.get("cost_eur", 0.0)),
                float(e.get("duration_sec", 0.0)),
                e.get("error"),
            ))
        except Exception:
            pass


def _migrate_settings(conn: sqlite3.Connection) -> None:
    path = BASE_DIR / "config" / "settings.json"
    data = _load_json(path, {})

    for key, value in data.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value))
        )
