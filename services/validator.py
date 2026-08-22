from dataclasses import dataclass
from decimal import Decimal
from services.registry import Registry


@dataclass
class ValidationResult:
    allowed: bool
    reason: str


class Validator:
    """
    Central permission gate. Called before any agent/tool runs.
    All checks return ValidationResult(allowed, reason).
    """

    def __init__(self, registry: Registry):
        self.registry = registry

    @staticmethod
    def _money(value) -> Decimal:
        """Convert display/API numbers without importing their float error."""
        return Decimal(str(value))

    def validate(
        self,
        agent_name: str,
        tool_name: str,
        provider: str,
        api_permissions: dict[str, bool],
        session_cost: float,
        session_budget: float,
        daily_cost: float,
        daily_budget: float,
        estimated_cost: float,
        project_name: str = "",
        project_cost: float = 0.0,
        project_budget: float | None = None,
    ) -> ValidationResult:
        # 1. Agent enabled?
        if not self.registry.is_agent_enabled(agent_name):
            return ValidationResult(False, f"Agent '{agent_name}' is disabled in the registry.")

        # 2. Tool enabled? (skip for audiobook which has no tool)
        if tool_name and not self.registry.is_tool_enabled(tool_name):
            return ValidationResult(False, f"Tool '{tool_name}' is disabled in the registry.")

        # 3. Provider allowed for this agent?
        if not self.registry.agent_allows_provider(agent_name, provider):
            return ValidationResult(
                False,
                f"Agent '{agent_name}' does not permit provider '{provider}'."
            )

        # 4. Provider allowed for this tool?
        if tool_name and not self.registry.tool_allows_provider(tool_name, provider):
            return ValidationResult(
                False,
                f"Tool '{tool_name}' does not permit provider '{provider}'."
            )

        # 5. Tool allowed for this agent?
        if tool_name and not self.registry.agent_allows_tool(agent_name, tool_name):
            return ValidationResult(
                False,
                f"Agent '{agent_name}' does not permit tool '{tool_name}'."
            )

        # 6. API checkbox permission (free pass for ollama)
        if provider != "ollama":
            perm_key = f"allow_{provider}"
            if not api_permissions.get(perm_key, False):
                return ValidationResult(
                    False,
                    f"API access for '{provider}' is not enabled. Enable it in the API Permissions panel."
                )

        # 7. Per-agent budget (daily)
        agent_budget = self.registry.get_agent_budget(agent_name)
        if agent_budget is not None and provider != "ollama":
            if self._money(estimated_cost) > self._money(agent_budget):
                return ValidationResult(
                    False,
                    f"Agent '{agent_name}' has a budget cap of €{agent_budget:.2f}/day. "
                    f"This request is estimated at €{estimated_cost:.4f}."
                )

        # 8. Active project daily budget
        if project_budget is not None and provider != "ollama":
            project_remaining = self._money(project_budget) - self._money(project_cost)
            if self._money(estimated_cost) > project_remaining:
                return ValidationResult(
                    False,
                    f"Project '{project_name}' budget exceeded. Remaining: "
                    f"€{project_remaining:.4f}, request: ~€{estimated_cost:.4f}."
                )

        # 9. Session budget
        if provider != "ollama":
            session_remaining = self._money(session_budget) - self._money(session_cost)
            if self._money(estimated_cost) > session_remaining:
                return ValidationResult(
                    False,
                    f"Session budget exceeded. "
                    f"Remaining: €{session_remaining:.4f}, request: ~€{estimated_cost:.4f}."
                )

        # 10. Daily budget
        if provider != "ollama":
            daily_remaining = self._money(daily_budget) - self._money(daily_cost)
            if self._money(estimated_cost) > daily_remaining:
                return ValidationResult(
                    False,
                    f"Daily budget exceeded. "
                    f"Remaining: €{daily_remaining:.4f}, request: ~€{estimated_cost:.4f}."
                )

        # 11. Approval required?
        if self.registry.agent_requires_approval(agent_name):
            return ValidationResult(
                False,
                f"Agent '{agent_name}' requires manual approval before running."
            )

        return ValidationResult(True, "OK")
