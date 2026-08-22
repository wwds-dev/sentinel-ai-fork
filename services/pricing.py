"""Fail-safe pricing and request cost estimates."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any


class PricingUnavailable(RuntimeError):
    """Raised when a cloud request cannot be priced safely."""


@dataclass(frozen=True)
class PriceQuote:
    backend: str
    model: str
    available: bool
    reason: str = ""
    input_per_1m_usd: float | None = None
    cached_input_per_1m_usd: float | None = None
    output_per_1m_usd: float | None = None
    source: str | None = None
    verified_at: str | None = None
    region: str | None = None
    tier: str | None = None
    status: str = "unknown"

    @property
    def label(self) -> str:
        if not self.available:
            return "price unavailable"
        return f"${self.input_per_1m_usd:g} in / ${self.output_per_1m_usd:g} out per 1M"


@dataclass(frozen=True)
class CostEstimate:
    available: bool
    minimum_eur: float | None
    maximum_eur: float | None
    input_tokens: int
    output_tokens_min: int
    output_tokens_max: int
    reason: str = ""
    quote: PriceQuote | None = None

    @property
    def midpoint_eur(self) -> float:
        if not self.available or self.minimum_eur is None or self.maximum_eur is None:
            raise PricingUnavailable(self.reason or "Cost is unavailable")
        return round((self.minimum_eur + self.maximum_eur) / 2, 6)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def quote_from_row(backend: str, model: str, row: Any, *, max_age_days: int = 120,
                   today: date | None = None) -> PriceQuote:
    if backend == "ollama":
        return PriceQuote(backend, model, True, status="local", source="local execution",
                          input_per_1m_usd=0.0, output_per_1m_usd=0.0)
    if row is None:
        return PriceQuote(backend, model, False, "No verified price for this cloud model")
    data = dict(row)
    status = str(data.get("price_status") or data.get("status") or "unknown").lower()
    if status != "active":
        return PriceQuote(backend, model, False, f"Price status is {status}", status=status)
    verified = str(data.get("verified_at") or "")
    checked = parse_date(verified)
    if checked is None:
        return PriceQuote(backend, model, False, "Price has no verification date", status=status)
    age = ((today or datetime.now(timezone.utc).date()) - checked).days
    if age < 0 or age > max_age_days:
        return PriceQuote(backend, model, False, f"Price verification is stale ({age} days)", verified_at=verified, status="stale")
    inp, out = data.get("input_per_1m_usd"), data.get("output_per_1m_usd")
    if inp is None or out is None or float(inp) < 0 or float(out) < 0:
        return PriceQuote(backend, model, False, "Price rates are incomplete", status="invalid")
    return PriceQuote(backend, model, True, input_per_1m_usd=float(inp),
        cached_input_per_1m_usd=(float(data["cached_input_per_1m_usd"]) if data.get("cached_input_per_1m_usd") is not None else None),
        output_per_1m_usd=float(out), source=data.get("price_source"), verified_at=verified,
        region=data.get("price_region"), tier=data.get("price_tier"), status=status)


def validate_fx(rate: float | None, verified_at: str | None, *, max_age_days: int = 14,
                today: date | None = None) -> tuple[bool, str]:
    if rate is None or not (0 < float(rate) < 10):
        return False, "EUR/USD conversion rate is missing or invalid"
    checked = parse_date(verified_at)
    if checked is None:
        return False, "EUR/USD conversion rate has no verification date"
    age = ((today or datetime.now(timezone.utc).date()) - checked).days
    if age < 0 or age > max_age_days:
        return False, f"EUR/USD conversion rate is stale ({age} days)"
    return True, ""
