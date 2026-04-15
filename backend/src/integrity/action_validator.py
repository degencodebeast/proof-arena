"""ActionValidator — pre-execution validation for agent actions.

Deterministic benchmark integrity. No LLM judgment.
Checks: action type, quote existence, freshness, slippage, route whitelist, budget, WAIT bounds.
"""

from __future__ import annotations

from typing import Any

from src.db.schemas import AgentActionType
from src.integrity import ValidationResult
from src.services.jupiter_service import JupiterService


class ActionValidator:
    """Concrete V1 action validator for swap execution benchmarks."""

    def __init__(
        self,
        jupiter_service: JupiterService,
        challenge_config: dict[str, Any],
    ):
        self.jupiter = jupiter_service
        self.allowed_actions = {
            AgentActionType.EXECUTE_SWAP,
            AgentActionType.WAIT,
            AgentActionType.FINISH,
        }
        self.max_slippage_bps: int = challenge_config.get("max_slippage_bps", 500)
        self.allowed_routes: list[list[str]] = challenge_config.get("allowed_routes", [])
        self.quote_max_age_secs: int = challenge_config.get("quote_max_age_secs", 30)

    async def validate(
        self, action: dict[str, Any], state: dict[str, Any]
    ) -> ValidationResult:
        """Validate an agent action against all constraints."""
        action_type_str = action.get("type", "")
        try:
            action_type = AgentActionType(action_type_str)
        except ValueError:
            return ValidationResult(
                valid=False,
                reason=f"Unknown action type: {action_type_str}",
            )

        if action_type not in self.allowed_actions:
            return ValidationResult(
                valid=False,
                reason=f"Action type {action_type_str} not allowed",
            )

        if action_type == AgentActionType.FINISH:
            return ValidationResult(valid=True)

        if action_type == AgentActionType.WAIT:
            return self._validate_wait(action)

        if action_type == AgentActionType.EXECUTE_SWAP:
            return self._validate_swap(action, state)

        return ValidationResult(valid=False, reason="Unhandled action type")

    def _validate_wait(self, action: dict[str, Any]) -> ValidationResult:
        params = action.get("params", {})
        seconds = params.get("seconds", 0)
        if not isinstance(seconds, int) or seconds < 1 or seconds > 60:
            return ValidationResult(
                valid=False,
                reason=f"WAIT seconds must be 1-60, got {seconds}",
                details={"seconds": seconds},
            )
        return ValidationResult(valid=True)

    def _validate_swap(
        self, action: dict[str, Any], state: dict[str, Any]
    ) -> ValidationResult:
        params = action.get("params", {})
        quote_id = params.get("quote_id")
        max_slippage = params.get("max_slippage_bps", 0)

        # Quote existence
        if not quote_id:
            return ValidationResult(
                valid=False, reason="Missing quote_id",
            )

        # Quote freshness
        if not self.jupiter.is_quote_fresh(quote_id, self.quote_max_age_secs):
            return ValidationResult(
                valid=False,
                reason="stale_quote",
                details={"quote_id": quote_id, "max_age_secs": self.quote_max_age_secs},
            )

        # Quote existence (explicit check after freshness)
        quote = self.jupiter.get_cached_quote(quote_id)
        if quote is None:
            return ValidationResult(
                valid=False,
                reason="Quote not found in cache",
                details={"quote_id": quote_id},
            )

        # Slippage bounds
        if max_slippage > self.max_slippage_bps:
            return ValidationResult(
                valid=False,
                reason=f"Slippage {max_slippage} exceeds max {self.max_slippage_bps}",
                details={"requested": max_slippage, "max": self.max_slippage_bps},
            )

        # Route whitelist
        if self.allowed_routes:
            route = [quote.input_mint, quote.output_mint]
            if route not in self.allowed_routes:
                return ValidationResult(
                    valid=False,
                    reason=f"Route {route} not in allowed routes",
                    details={"route": route, "allowed": self.allowed_routes},
                )

        # Iteration budget
        iterations_used = state.get("iterations_used", 0)
        iteration_budget = state.get("iteration_budget", 0)
        if iteration_budget > 0 and iterations_used >= iteration_budget:
            return ValidationResult(
                valid=False,
                reason="Iteration budget exceeded",
                details={"used": iterations_used, "budget": iteration_budget},
            )

        return ValidationResult(valid=True)
