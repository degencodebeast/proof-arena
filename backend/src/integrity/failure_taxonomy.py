"""V2 failure taxonomy — authoritative forward source of truth for V2 work.

Two enums serve three V2 consumer surfaces without blurring them:

- ``SagaFailureReason`` — populated on ``agent_instances.last_failure_reason``
  when an instance deploy saga fails at step 3/5/6. Owned by operator repair
  flows (see plan B-10). No user-visible messaging directly references these.

- ``RunInvalidReason`` — populated on ``runs.invalid_reason`` when a benchmark
  run is classified invalid by the runner / ``ActionValidator`` / settlement
  verifier. V1 values are preserved byte-equal (pre-existing rows must remain
  valid); V2 adds five reasons introduced by the hosted-runtime path.

Every new V2 code path that records a failure MUST use a named enum member
from this module. Free-text values are rejected at the DB layer via CHECK
constraints (see this task's Alembic migration for ``runs.invalid_reason``
and Task 2 for ``agent_instances.last_failure_reason``).

Transitional coexistence with V1. This module does NOT delete the legacy
``db.schemas.InvalidReason`` enum. V1 values are redeclared on
``RunInvalidReason`` byte-equal so pre-existing ``runs.invalid_reason`` rows
stay valid under the new CHECK. Migrating existing V1 consumers to import
from this module is intentionally out of Task 1 scope — that is a separate,
broader refactor. While it is pending, both enums coexist; the A-6 test
``test_run_invalid_reason_preserves_v1_strings`` locks byte-equality so they
cannot silently drift.

Human-readable labels for each member live in ``failure_taxonomy_copy`` and
are served to the frontend via ``GET /api/v1/failure-taxonomy``.
"""

from __future__ import annotations

from enum import Enum


class SagaFailureReason(str, Enum):
    """Deploy-saga failure states for ``agent_instances.last_failure_reason``.

    The saga lifecycle enum itself (``agent_instances.status``) is authored in
    Task 2 alongside the column expansion; this module owns only the set of
    reasons that may populate ``last_failure_reason`` when a saga lands in a
    ``*_failed`` state.
    """

    PROVISIONING_FAILED = "provisioning_failed"
    WALLET_CREATED_RUNTIME_FAILED = "wallet_created_runtime_failed"
    RUNTIME_LIVE_CONSENT_FAILED = "runtime_live_consent_failed"


class RunInvalidReason(str, Enum):
    """Reasons a benchmark run is classified invalid.

    V1 values (preserved byte-equal to ``db.schemas.InvalidReason``) must
    remain valid for pre-existing ``runs`` rows. V2 values are added below;
    any future addition requires an enum member, a copy-map entry, and an
    Alembic migration that expands the CHECK constraint.
    """

    # --- V1 preserved (see db/schemas.py::InvalidReason) --------------
    INCOMPLETE_REQUIRED_ACTIONS = "incomplete_required_actions"
    INVALID_ACTION_ATTEMPTS_EXCEEDED = "invalid_action_attempts_exceeded"
    STALE_QUOTE_EXECUTION_FAILED = "stale_quote_execution_failed"
    TIMEOUT_BEFORE_COMPLETION = "timeout_before_completion"
    FLATTENING_FAILED = "flattening_failed"
    EXECUTION_ERROR = "execution_error"

    # --- V2 additions (hosted-runtime path) ---------------------------
    MAINNET_GUARD_TRIGGERED = "mainnet_guard_triggered"
    WALLET_POLICY_REJECTED = "wallet_policy_rejected"
    RUNTIME_INVOCATION_FAILED = "runtime_invocation_failed"
    AUTHORIZATION_SIGNATURE_REJECTED = "authorization_signature_rejected"
    HOSTED_WALLET_UNAVAILABLE = "hosted_wallet_unavailable"


def run_invalid_reason_values() -> tuple[str, ...]:
    """Return the full set of valid ``runs.invalid_reason`` string values.

    Used by the Alembic migration and model-level CHECK constraint to avoid
    duplicating the enum vocabulary in raw SQL.
    """

    return tuple(m.value for m in RunInvalidReason)


def saga_failure_reason_values() -> tuple[str, ...]:
    """Return the full set of valid ``agent_instances.last_failure_reason`` values.

    Consumed by Task 2 when it adds the column + CHECK.
    """

    return tuple(m.value for m in SagaFailureReason)
