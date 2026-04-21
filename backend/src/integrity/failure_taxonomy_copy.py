"""Human-readable copy for every member of the V2 failure taxonomy.

Consumed by the frontend via ``GET /api/v1/failure-taxonomy`` to render
consistent labels for failure reasons across flagship, instance, and
operator surfaces. The mapping is enforced complete by the A-6 unit tests;
adding a new enum member without a copy entry fails ``test_copy_map_covers_all_enum_members``.

Copy conventions:
- ``title`` — short label (≤40 chars) suitable for badges / column cells
- ``description`` — one sentence, user-facing, no operator-internal jargon
"""

from __future__ import annotations

from typing import TypedDict

from src.integrity.failure_taxonomy import RunInvalidReason, SagaFailureReason


class FailureCopy(TypedDict):
    title: str
    description: str


FAILURE_COPY_MAP: dict[SagaFailureReason | RunInvalidReason, FailureCopy] = {
    # -- Saga failure reasons -----------------------------------------
    # Public-safe copy. Keep the three states user-distinguishable (early
    # failure / partial setup / not finalized) without surfacing internal
    # terms like wallet/runtime/consent-artifact or repair semantics.
    SagaFailureReason.PROVISIONING_FAILED: {
        "title": "Deployment failed",
        "description": "This instance could not start deploying.",
    },
    SagaFailureReason.WALLET_CREATED_RUNTIME_FAILED: {
        "title": "Deployment incomplete",
        "description": (
            "This instance started deploying but did not finish. "
            "It is not available for benchmarks."
        ),
    },
    SagaFailureReason.RUNTIME_LIVE_CONSENT_FAILED: {
        "title": "Deployment not finalized",
        "description": (
            "This instance finished deploying but was not finalized. "
            "It is not available for benchmarks."
        ),
    },
    # -- Run invalid reasons (V1 preserved) ---------------------------
    RunInvalidReason.INCOMPLETE_REQUIRED_ACTIONS: {
        "title": "Incomplete required actions",
        "description": (
            "The agent did not complete the challenge's required action "
            "set before finishing."
        ),
    },
    RunInvalidReason.INVALID_ACTION_ATTEMPTS_EXCEEDED: {
        "title": "Too many invalid actions",
        "description": (
            "The agent exceeded the allowed number of invalid action "
            "attempts in a single run."
        ),
    },
    RunInvalidReason.STALE_QUOTE_EXECUTION_FAILED: {
        "title": "Stale quote",
        "description": (
            "Execution failed because the quote used was no longer fresh "
            "by the time the swap was submitted."
        ),
    },
    RunInvalidReason.TIMEOUT_BEFORE_COMPLETION: {
        "title": "Timed out",
        "description": (
            "The agent did not complete the challenge within its time budget."
        ),
    },
    RunInvalidReason.FLATTENING_FAILED: {
        "title": "Flattening failed",
        "description": (
            "Post-run flattening to USDC could not be completed; ending "
            "value cannot be measured reliably."
        ),
    },
    RunInvalidReason.EXECUTION_ERROR: {
        "title": "Execution error",
        "description": (
            "An execution-side error prevented the run from completing "
            "cleanly."
        ),
    },
    # -- Run invalid reasons (V2 additions) ---------------------------
    RunInvalidReason.MAINNET_GUARD_TRIGGERED: {
        "title": "Mainnet guard triggered",
        "description": (
            "The run attempted a transaction that was rejected by the "
            "devnet-only mainnet guard."
        ),
    },
    RunInvalidReason.WALLET_POLICY_REJECTED: {
        "title": "Wallet policy rejected",
        "description": (
            "The hosted wallet's enclave policy rejected a transaction "
            "because it targeted a program outside the allowlist."
        ),
    },
    RunInvalidReason.RUNTIME_INVOCATION_FAILED: {
        "title": "Runtime error",
        "description": (
            "The hosted runtime surfaced an error during a decide step."
        ),
    },
    RunInvalidReason.AUTHORIZATION_SIGNATURE_REJECTED: {
        "title": "Authorization rejected",
        "description": (
            "The hosted wallet provider rejected the request's "
            "authorization signature."
        ),
    },
    RunInvalidReason.HOSTED_WALLET_UNAVAILABLE: {
        "title": "Hosted wallet unavailable",
        "description": (
            "The hosted wallet was not reachable or had insufficient "
            "resources to complete the run."
        ),
    },
}
