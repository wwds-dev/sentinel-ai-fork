from datetime import date
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.model_router import ModelCandidate, ModelRouter, RoutingPreferences
from services.pricing import CostEstimate, quote_from_row, validate_fx


def cost(low=0.01, high=0.02):
    return CostEstimate(True, low, high, 1000, 500, 2000)


def candidate(provider, model, **kwargs):
    defaults = dict(credentials=True, service_healthy=True, model_available=True,
                    context_window=128_000, capabilities=frozenset({"coding", "heavy"}),
                    cost=cost())
    defaults.update(kwargs)
    return ModelCandidate(provider, model, **defaults)


def test_routing_is_deterministic_independent_of_candidate_order():
    router = ModelRouter()
    prefs = RoutingPreferences(task="coding", complexity="heavy", required_context=10_000)
    a = candidate("qwen", "qwen-coder")
    b = candidate("openai", "gpt-code")
    first = router.recommend([a, b], prefs)
    second = router.recommend([b, a], prefs)
    assert (first.provider, first.model) == (second.provider, second.model)


def test_qwen_uses_the_same_eligibility_path_as_every_provider():
    router = ModelRouter()
    qwen = candidate("qwen", "qwen-coder")
    result = router.evaluate(qwen, RoutingPreferences(task="coding", complexity="heavy"))
    assert result.eligible
    assert "strong coding fit" in result.reasons


def test_qwen_without_credentials_is_ineligible():
    result = ModelRouter().evaluate(
        candidate("qwen", "qwen-coder", credentials=False), RoutingPreferences())
    assert not result.eligible
    assert "credentials unavailable" in result.blockers


def test_unknown_pricing_removes_cloud_candidate_and_falls_back_local():
    router = ModelRouter()
    unknown = CostEstimate(False, None, None, 100, 100, 500, "unknown")
    cloud = candidate("qwen", "qwen-coder", cost=unknown)
    local = candidate("ollama", "local", local=True, credentials=False, cost=cost(0, 0))
    recommendation = router.recommend([cloud, local], RoutingPreferences(task="coding"))
    assert recommendation.provider == "ollama"
    assert router.fallback_chain(recommendation) == (("ollama", "local"),)


def test_budget_uses_high_end_of_cost_range():
    result = ModelRouter().evaluate(candidate("qwen", "qwen", cost=cost(0.01, 0.20)),
                                    RoutingPreferences(budget_eur=0.10))
    assert not result.eligible
    assert "estimated maximum exceeds budget" in result.blockers


def test_stale_price_and_fx_are_unavailable():
    row = {"input_per_1m_usd": 1, "output_per_1m_usd": 2, "price_status": "active",
           "verified_at": "2025-01-01"}
    assert not quote_from_row("qwen", "qwen", row, today=date(2026, 8, 22)).available
    valid, reason = validate_fx(0.92, "2025-01-01", today=date(2026, 8, 22))
    assert not valid and "stale" in reason


def test_recommendation_reasons_include_cost_range():
    rec = ModelRouter().recommend([candidate("qwen", "qwen")], RoutingPreferences(task="coding"))
    assert any("estimated €" in reason for reason in rec.reasons)
