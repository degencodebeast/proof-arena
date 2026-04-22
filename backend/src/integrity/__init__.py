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
class ActionValidatorProtocol(Protocol):
    """Protocol for pre-execution action validation."""

    async def validate(
        self, action: dict[str, Any], state: dict[str, Any]
    ) -> ValidationResult:
        ...


# Re-export concrete implementations for clean imports
from src.integrity.action_validator import ActionValidator  # noqa: E402
from src.integrity.completion_evaluator import CompletionEvaluator  # noqa: E402
from src.integrity.run_auditor import RunAuditor  # noqa: E402
from src.integrity.settlement_verifier import SettlementEligibility, SettlementVerifier  # noqa: E402
from src.integrity.trust_labels import TrustLabel, trust_label_values  # noqa: E402
from src.integrity.subject_types import SubjectType, subject_type_values  # noqa: E402
from src.integrity.saga_statuses import SagaStatus, saga_status_values  # noqa: E402

__all__ = [
    "ValidationResult",
    "ActionValidatorProtocol",
    "ActionValidator",
    "CompletionEvaluator",
    "RunAuditor",
    "SettlementVerifier",
    "SettlementEligibility",
    "TrustLabel",
    "trust_label_values",
    "SubjectType",
    "subject_type_values",
    "SagaStatus",
    "saga_status_values",
]
