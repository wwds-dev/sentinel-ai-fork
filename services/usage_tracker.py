from datetime import datetime
from services.database import get_connection
from services.pricing import CostEstimate, PricingUnavailable, quote_from_row, validate_fx


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

    def get_price_quote(self, backend: str, model: str):
        if backend == "ollama":
            return quote_from_row(backend, model, None)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM pricing WHERE backend = ? AND model IN (?, 'default') "
                "ORDER BY CASE model WHEN ? THEN 0 ELSE 1 END LIMIT 1",
                (backend, model, model),
            ).fetchone()
        return quote_from_row(backend, model, row)

    def estimate_cost_range(self, backend: str, model: str, input_tokens: int,
                            output_tokens_min: int, output_tokens_max: int) -> CostEstimate:
        quote = self.get_price_quote(backend, model)
        if not quote.available:
            return CostEstimate(False, None, None, input_tokens, output_tokens_min,
                                output_tokens_max, quote.reason, quote)
        if backend == "ollama":
            return CostEstimate(True, 0.0, 0.0, input_tokens, output_tokens_min,
                                output_tokens_max, quote=quote)
        with get_connection() as conn:
            rate_row = conn.execute("SELECT value FROM settings WHERE key='eur_per_usd'").fetchone()
            date_row = conn.execute("SELECT value FROM settings WHERE key='eur_per_usd_verified_at'").fetchone()
        rate = float(rate_row["value"]) if rate_row else None
        verified_at = date_row["value"] if date_row else None
        valid, reason = validate_fx(rate, verified_at)
        if not valid:
            return CostEstimate(False, None, None, input_tokens, output_tokens_min,
                                output_tokens_max, reason, quote)
        base = input_tokens / 1_000_000 * quote.input_per_1m_usd
        low = (base + output_tokens_min / 1_000_000 * quote.output_per_1m_usd) * rate
        high = (base + output_tokens_max / 1_000_000 * quote.output_per_1m_usd) * rate
        return CostEstimate(True, round(low, 6), round(high, 6), input_tokens,
                            output_tokens_min, output_tokens_max, quote=quote)

    def calculate_cost_eur(self, backend: str, model: str, input_tokens: int,
                           output_tokens: int, cached_input_tokens: int = 0) -> float:
        if backend == "ollama":
            return 0.0

        with get_connection() as conn:
            eur_row = conn.execute("SELECT value FROM settings WHERE key = 'eur_per_usd'").fetchone()
            eur_per_usd = float(eur_row["value"]) if eur_row else None
            fx_date = conn.execute("SELECT value FROM settings WHERE key = 'eur_per_usd_verified_at'").fetchone()

            row = conn.execute(
                "SELECT input_per_1m_usd, cached_input_per_1m_usd, output_per_1m_usd "
                "FROM pricing WHERE backend = ? AND model IN (?, 'default') "
                "ORDER BY CASE model WHEN ? THEN 0 ELSE 1 END LIMIT 1",
                (backend, model, model)
            ).fetchone()

        quote = self.get_price_quote(backend, model)
        if not quote.available:
            raise PricingUnavailable(quote.reason)
        valid_fx, fx_reason = validate_fx(eur_per_usd, fx_date["value"] if fx_date else None)
        if not valid_fx:
            raise PricingUnavailable(fx_reason)
        if not row:
            raise PricingUnavailable("No verified price for this cloud model")

        cached_input_tokens = max(0, min(int(cached_input_tokens), input_tokens))
        ordinary_input_tokens = input_tokens - cached_input_tokens
        cached_rate = row["cached_input_per_1m_usd"]
        if cached_rate is None:
            cached_rate = row["input_per_1m_usd"]
        input_usd = (
            ordinary_input_tokens / 1_000_000 * row["input_per_1m_usd"]
            + cached_input_tokens / 1_000_000 * cached_rate
        )
        output_usd = (output_tokens / 1_000_000) * row["output_per_1m_usd"]
        return round((input_usd + output_usd) * eur_per_usd, 6)

    def log_request(self, agent: str, backend: str, model: str,
                    prompt_text: str, response_text: str, usage: dict | None = None,
                    project: str | None = None) -> dict:
        input_tokens, output_tokens, cost_type = self.normalize_usage(usage, prompt_text, response_text)
        cached_input_tokens = int((usage or {}).get("cached_input_tokens") or 0)
        cost_eur = self.calculate_cost_eur(
            backend, model, input_tokens, output_tokens, cached_input_tokens)
        if cached_input_tokens and cost_type == "exact":
            cost_type = "exact-cached"
        timestamp = datetime.now().isoformat(timespec="seconds")

        with get_connection() as conn:
            conn.execute("""
                INSERT INTO usage
                  (timestamp, agent, backend, model, input_tokens, output_tokens,
                   total_tokens, cost_eur, cost_type, cloud, project)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                timestamp, agent, backend, model,
                input_tokens, output_tokens, input_tokens + output_tokens,
                cost_eur, cost_type,
                0 if backend == "ollama" else 1, project,
            ))
            conn.commit()

        return {
            "timestamp": timestamp,
            "agent": agent,
            "backend": backend,
            "model": model,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost_eur": cost_eur,
            "estimated_cost": cost_eur,
            "cost_type": cost_type,
            "cloud": backend != "ollama",
            "project": project,
        }

    def get_project_total_today(self, project: str | None) -> float:
        if not project:
            return 0.0
        today = datetime.now().date().isoformat()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_eur), 0.0) AS total FROM usage "
                "WHERE project = ? AND timestamp LIKE ?",
                (project, f"{today}%"),
            ).fetchone()
        return round(float(row["total"]), 6)

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
