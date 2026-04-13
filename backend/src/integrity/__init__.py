"""Integrity layer — action validation, completion evaluation,
run auditing, and settlement verification.

Boundary rule: Integrity components enforce deterministic rules.
They must NOT use LLM judgment for completion validity, settlement truth,
or winner determination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ValidationResult:
    """Result of validating an agent action."""

    valid: bool
    reason: str | None = None
    details: dict[str, Any] | None = None


@runtime_checkable
class ActionValidator(Protocol):
    """Protocol for pre-execution action validation.

    Checks: schema validity, action whitelist, quote freshness,
    slippage bounds, route whitelist, iteration budget.
    """

    async def validate(
        self, action: dict[str, Any], state: dict[str, Any]
    ) -> ValidationResult:
        """Validate an agent action against all constraints."""
        ...
