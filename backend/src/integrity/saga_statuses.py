"""V2 saga-status contract — single source of truth for
``agent_instances.status``.

Seven lifecycle states form the deploy saga state machine (see plan §3
"agent_instances" schema and §10 invariants 1, 4):

- ``PROVISIONING`` — saga started; wallet + runtime + consent not yet complete.
- ``WALLET_CREATED_RUNTIME_FAILED`` — Privy wallet exists, AgentOS runtime
  deploy failed. Operator repair path: inspect + teardown.
- ``RUNTIME_LIVE_CONSENT_FAILED`` — runtime up, consent artifact write
  failed. Operator repair path: retry consent or teardown.
- ``PROVISIONING_FAILED`` — catch-all early failure. No wallet, no runtime.
- ``LIVE`` — happy-path terminal for active instances.
- ``PAUSED`` — operator paused the instance.
- ``TORN_DOWN`` — runtime torn down; terminal state.

Non-``live`` instances cannot be benchmarked; that rule is enforced by
``challenge_service.create_run_for_instance`` (Task 15 scope), not here.

``last_failure_reason`` populates only when ``status`` is one of the
three ``*_failed`` states; the allowed vocabulary for that column is
``SagaFailureReason`` in ``failure_taxonomy.py``.

Because ``db.models`` cannot import from the ``src.integrity`` package
(circular via its eager ``__init__``), the CHECK list is duplicated as a
tuple in ``db.models`` and held in sync with this enum by a drift-guard
test.
"""

from __future__ import annotations

from enum import Enum


class SagaStatus(str, Enum):
    """Lifecycle states for ``agent_instances.status``.

    See module docstring for the state-machine rationale.
    """

    PROVISIONING = "provisioning"
    WALLET_CREATED_RUNTIME_FAILED = "wallet_created_runtime_failed"
    RUNTIME_LIVE_CONSENT_FAILED = "runtime_live_consent_failed"
    PROVISIONING_FAILED = "provisioning_failed"
    LIVE = "live"
    PAUSED = "paused"
    TORN_DOWN = "torn_down"


def saga_status_values() -> tuple[str, ...]:
    """Return the full set of valid ``agent_instances.status`` strings.

    Consumed by callers building CHECK SQL or API responses — keeps them
    from hardcoding the vocabulary in multiple places.
    """

    return tuple(m.value for m in SagaStatus)
