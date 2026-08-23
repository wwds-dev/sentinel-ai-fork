from datetime import datetime
from services.database import get_connection
from services.provider_catalog import CLOUD_PROVIDERS


class UsageTracker:
    def estimate_tokens(self, prompt_text: str, response_text: str) -> tuple[int, int]:
        return max(1, len(prompt_text) // 4), max(1, len(response_text) // 4)

    def normalize_usage(self, usage: dict | None, prompt_text: str, response_text: str) -> tuple[int, int, str]:
        if not usage:
            i, o = self.estimate_tokens(prompt_text, response_text)
            return i, o, "estimated"

        override = usage.get("cost_type_override")

        i = int(usage.get("input_tokens") or usage.get("prompt_tokens") or usage.get("prompt_token_count") or 0)
        o = int(usage.get("output_tokens") or usage.get("completion_tokens") or usage.get("candidates_token_count") or 0)

        if i <= 0 or o <= 0:
            ei, eo = self.estimate_tokens(prompt_text, response_text)
            return i or ei, o or eo, override or "mixed"

        return i, o, override or "exact"

    def load_pricing(self) -> dict:
        result = {"eur_per_usd": 0.92}
        with get_connection() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = 'eur_per_usd'").fetchone()
            if row:
                result["eur_per_usd"] = float(row["value"])

            for r in conn.execute("SELECT backend, model, input_per_1m_usd, output_per_1m_usd FROM pricing"):
                backend = r["backend"]
                result.setdefault(backend, {})
                result[backend][r["model"]] = {
                    "input_per_1m_usd": r["input_per_1m_usd"],
                    "output_per_1m_usd": r["output_per_1m_usd"],
                }
        return result

    def calculate_cost_eur(self, backend: str, model: str, input_tokens: int, output_tokens: int) -> float:
        if backend == "ollama":
            return 0.0

        with get_connection() as conn:
            eur_row = conn.execute("SELECT value FROM settings WHERE key = 'eur_per_usd'").fetchone()
            eur_per_usd = float(eur_row["value"]) if eur_row else 0.92

            row = conn.execute(
                "SELECT input_per_1m_usd, output_per_1m_usd FROM pricing WHERE backend = ? AND model IN (?, 'default') ORDER BY CASE model WHEN ? THEN 0 ELSE 1 END LIMIT 1",
                (backend, model, model)
            ).fetchone()

        if not row:
            return 0.0

        input_usd = (input_tokens / 1_000_000) * row["input_per_1m_usd"]
        output_usd = (output_tokens / 1_000_000) * row["output_per_1m_usd"]
        return round((input_usd + output_usd) * eur_per_usd, 6)

    def log_request(self, agent: str, backend: str, model: str,
                    prompt_text: str, response_text: str, usage: dict | None = None) -> dict:
        input_tokens, output_tokens, cost_type = self.normalize_usage(usage, prompt_text, response_text)
        cost_eur = self.calculate_cost_eur(backend, model, input_tokens, output_tokens)
        timestamp = datetime.now().isoformat(timespec="seconds")

        with get_connection() as conn:
            conn.execute("""
                INSERT INTO usage
                  (timestamp, agent, backend, model, input_tokens, output_tokens,
                   total_tokens, cost_eur, cost_type, cloud)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                timestamp, agent, backend, model,
                input_tokens, output_tokens, input_tokens + output_tokens,
                cost_eur, cost_type,
                1 if backend in CLOUD_PROVIDERS else 0,
            ))
            conn.commit()

        return {
            "timestamp": timestamp,
            "agent": agent,
            "backend": backend,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_eur": cost_eur,
            "estimated_cost": cost_eur,
            "cost_type": cost_type,
            "cloud": backend in CLOUD_PROVIDERS,
        }

    def get_today_total(self) -> float:
        today = datetime.now().date().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_eur), 0.0) AS total FROM usage WHERE timestamp LIKE ?",
                (f"{today}%",)
            ).fetchone()
        return round(float(row["total"]), 6)

    def get_total_requests_today(self) -> int:
        today = datetime.now().date().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM usage WHERE timestamp LIKE ?",
                (f"{today}%",)
            ).fetchone()
        return int(row["cnt"])

    def load_log(self) -> list:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM usage ORDER BY id ASC"
            ).fetchall()
        return [dict(r) for r in rows]
