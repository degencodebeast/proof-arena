"""CompletionEvaluator — benchmark validity classification.

Classifies a run as complete, incomplete, or invalid based on events.
Deterministic rules only. No LLM judgment.

A run can be lifecycle "completed" but completion "incomplete" or "invalid".
"""

from __future__ import annotations

import json
from typing import Any

from src.challenges.base import CompletionResult

MAX_INVALID_ATTEMPTS = 10


class CompletionEvaluator:
    """Classifies benchmark validity from run events and final state."""

    def __init__(
        self,
        challenge_adapter: Any,
        max_invalid_attempts: int = MAX_INVALID_ATTEMPTS,
    ):
        self.adapter = challenge_adapter
        self.max_invalid_attempts = max_invalid_attempts

    async def evaluate(
        self,
        run_events: list[dict[str, Any]],
        final_balances: dict[str, int],
        run_status: str = "completed",
    ) -> CompletionResult:
        """Classify benchmark validity.

        Order of checks:
        1. Too many invalid action attempts → invalid
        2. Critical execution error → invalid
        3. Timeout → incomplete
        4. Delegate to challenge adapter for task-specific checks
        """
        # Count invalid validation attempts
        invalid_count = self._count_invalid_validations(run_events)
        if invalid_count > self.max_invalid_attempts:
            return CompletionResult(
                status="invalid",
                reason="invalid_action_attempts_exceeded",
                details={"invalid_count": invalid_count, "max": self.max_invalid_attempts},
            )

        # Check for critical execution errors
        critical_error = self._find_critical_error(run_events)
        if critical_error:
            return CompletionResult(
                status="invalid",
                reason="execution_error",
                details={"error": critical_error},
            )

        # Check timeout (explicit status or budget_exceeded event)
        if run_status == "timeout":
            return CompletionResult(
                status="incomplete",
                reason="timeout_before_completion",
            )

        budget_reason = self._find_budget_exceeded(run_events)
        if budget_reason:
            return CompletionResult(
                status="incomplete",
                reason="timeout_before_completion",
                details={"budget_reason": budget_reason},
            )

        # Delegate to challenge adapter
        return await self.adapter.validate_completion(run_events, final_balances)

    @staticmethod
    def _count_invalid_validations(events: list[dict[str, Any]]) -> int:
        """Count events where validation failed."""
        count = 0
        for event in events:
            if event.get("event_type") != "validate":
                continue
            payload = event.get("validation_payload_json")
            if payload is None:
                continue
            # Handle both dict and JSON string
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(payload, dict) and not payload.get("valid", True):
                count += 1
        return count

    @staticmethod
    def _find_critical_error(events: list[dict[str, Any]]) -> str | None:
        """Find a critical execution error in events."""
        for event in events:
            if event.get("event_type") != "error":
                continue
            payload = event.get("result_payload_json")
            if payload is None:
                continue
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    continue
            if isinstance(payload, dict):
                if payload.get("fatal"):
                    return payload.get("error", "Unknown fatal error")
        return None

    @staticmethod
    def _find_budget_exceeded(events: list[dict[str, Any]]) -> str | None:
        """Check if a budget_exceeded event exists."""
        for event in events:
            if event.get("event_type") == "budget_exceeded":
                payload = event.get("result_payload_json")
                if payload is None:
                    return "budget_exceeded"
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (json.JSONDecodeError, TypeError):
                        return "budget_exceeded"
                if isinstance(payload, dict):
                    return payload.get("reason", "budget_exceeded")
                return "budget_exceeded"
        return None
