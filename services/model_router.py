"""Provider-neutral deterministic model eligibility and scoring."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from services.pricing import CostEstimate

@dataclass(frozen=True)
class ModelCandidate:
    provider: str
    model: str
    enabled: bool = True
    credentials: bool = True
    service_healthy: bool = True
    model_available: bool = True
    context_window: int = 0
    local: bool = False
    latency: str = "medium"
    capabilities: frozenset[str] = field(default_factory=frozenset)
    cost: CostEstimate | None = None

@dataclass(frozen=True)
class RoutingPreferences:
    task: str = "general"
    complexity: str = "medium"
    required_context: int = 0
    budget_eur: float | None = None
    local_only: bool = False
    prefer_private: bool = False
    prefer_low_latency: bool = False

@dataclass(frozen=True)
class CandidateEvaluation:
    candidate: ModelCandidate
    eligible: bool
    score: int
    reasons: tuple[str, ...]
    blockers: tuple[str, ...]

@dataclass(frozen=True)
class Recommendation:
    provider: str | None
    model: str | None
    reasons: tuple[str, ...]
    evaluations: tuple[CandidateEvaluation, ...]

class ModelRouter:
    def __init__(self, settings_path: str = "config/settings.json"):
        self.settings_path = Path(settings_path)
    def load_settings(self) -> dict:
        return json.loads(self.settings_path.read_text(encoding="utf-8"))
    def save_hybrid_mode(self, enabled: bool) -> None:
        settings = self.load_settings(); settings["hybrid_mode"] = enabled
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    def classify_complexity(self, agent_name: str, user_text: str) -> str:
        text = user_text.lower()
        if any(k in text for k in ("architecture", "refactor", "debug", "traceback", "evaluate", "correlate")):
            return "very_heavy"
        if len(user_text) > 400 or agent_name in {"osint_heavy", "coding"}: return "heavy"
        if len(user_text) > 180: return "medium"
        return "light"
    def evaluate(self, candidate: ModelCandidate, prefs: RoutingPreferences) -> CandidateEvaluation:
        blockers, reasons, score = [], [], 0
        checks = ((candidate.enabled, "provider disabled"), (candidate.credentials or candidate.local, "credentials unavailable"),
                  (candidate.service_healthy, "service unhealthy"), (candidate.model_available, "model unavailable"))
        blockers.extend(message for ok, message in checks if not ok)
        if prefs.local_only and not candidate.local: blockers.append("local-only preference")
        if prefs.required_context and candidate.context_window < prefs.required_context: blockers.append("context window too small")
        if not candidate.local:
            if candidate.cost is None or not candidate.cost.available: blockers.append("verified pricing unavailable")
            elif prefs.budget_eur is not None and candidate.cost.maximum_eur > prefs.budget_eur: blockers.append("estimated maximum exceeds budget")
        if blockers: return CandidateEvaluation(candidate, False, -10_000, (), tuple(blockers))
        if candidate.local: score += 24; reasons.append("local and private")
        if prefs.prefer_private and candidate.local: score += 35; reasons.append("matches privacy preference")
        if prefs.task in candidate.capabilities: score += 40; reasons.append(f"strong {prefs.task} fit")
        if prefs.complexity in candidate.capabilities: score += 20; reasons.append(f"suited to {prefs.complexity} work")
        latency_score = {"low": 18, "medium": 9, "high": 0}.get(candidate.latency, 0)
        score += latency_score * (2 if prefs.prefer_low_latency else 1); reasons.append(f"{candidate.latency} latency")
        if candidate.cost and candidate.cost.available:
            score += max(0, 25 - min(25, round(candidate.cost.maximum_eur * 100)))
            reasons.append(f"estimated €{candidate.cost.minimum_eur:.4f}–€{candidate.cost.maximum_eur:.4f}")
        if candidate.context_window >= prefs.required_context: reasons.append("context requirement met")
        return CandidateEvaluation(candidate, True, score, tuple(reasons), ())
    def recommend(self, candidates: Iterable[ModelCandidate], prefs: RoutingPreferences) -> Recommendation:
        evaluations = tuple(self.evaluate(c, prefs) for c in candidates)
        eligible = [e for e in evaluations if e.eligible]
        if not eligible: return Recommendation(None, None, ("No eligible model",), evaluations)
        winner = sorted(eligible, key=lambda e: (-e.score, e.candidate.provider, e.candidate.model))[0]
        return Recommendation(winner.candidate.provider, winner.candidate.model, winner.reasons, evaluations)
    def fallback_chain(self, recommendation: Recommendation) -> tuple[tuple[str, str], ...]:
        ranked = sorted((e for e in recommendation.evaluations if e.eligible), key=lambda e: (-e.score, e.candidate.provider, e.candidate.model))
        return tuple((e.candidate.provider, e.candidate.model) for e in ranked)
    def choose_backend_and_model(self, agent_name: str, user_text: str, backend_override: str = "auto", model_override: str | None = None) -> tuple[str, str]:
        """Compatibility entry point; explicit user selections always win."""
        settings = self.load_settings()
        if backend_override != "auto":
            key = {"openai":"cloud_model", "deepseek":"deepseek_model", "kimi":"kimi_model", "gemini":"gemini_model", "qwen":"qwen_model", "anthropic":"anthropic_model"}.get(backend_override)
            return backend_override, model_override or settings.get(key or "", "")
        if model_override and not model_override.startswith("("): return "ollama", model_override
        complexity = self.classify_complexity(agent_name, user_text)
        return "ollama", settings["local_model_fallback" if complexity == "light" else "local_model_primary"]
    def get_cost_hint(self, backend: str, agent_name: str, complexity: str) -> tuple[str, str]:
        return (("Local / no API charge", "green") if backend == "ollama" else ("Cloud / verified price required", "yellow"))
