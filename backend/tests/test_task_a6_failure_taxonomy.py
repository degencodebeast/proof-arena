"""Task 1 / A-6 — RED tests for the failure taxonomy module.

Covers:
- SagaFailureReason + RunInvalidReason enum value locks
- V1 InvalidReason preservation (byte-equal strings)
- FAILURE_COPY_MAP coverage + shape + no orphans
- Enum value casing contract

See .taskmaster/docs/task1-edge-case-spec.md for the full edge-case spec.
"""

from __future__ import annotations

import os
import re

os.environ["ADMIN_API_KEY"] = "test-admin-key-a6"
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://test:test@localhost:5432/unused",
)


# Test 1 ---------------------------------------------------------------


def test_saga_failure_reason_values():
    """SagaFailureReason has exactly the 3 locked members."""
    from src.integrity.failure_taxonomy import SagaFailureReason

    members = {m.name: m.value for m in SagaFailureReason}
    assert members == {
        "PROVISIONING_FAILED": "provisioning_failed",
        "WALLET_CREATED_RUNTIME_FAILED": "wallet_created_runtime_failed",
        "RUNTIME_LIVE_CONSENT_FAILED": "runtime_live_consent_failed",
    }


# Test 2 ---------------------------------------------------------------


def test_run_invalid_reason_preserves_v1_strings():
    """RunInvalidReason preserves all 6 V1 values byte-equal to schemas.InvalidReason."""
    from src.db.schemas import InvalidReason as V1InvalidReason
    from src.integrity.failure_taxonomy import RunInvalidReason

    v2_values = {m.value for m in RunInvalidReason}

    for v1_member in V1InvalidReason:
        assert v1_member.value in v2_values, (
            f"V1 value {v1_member.value!r} is missing from RunInvalidReason; "
            "migration would break pre-existing runs"
        )


# Test 3 ---------------------------------------------------------------


def test_run_invalid_reason_adds_v2_values():
    """RunInvalidReason adds all 5 V2 values from the locked plan."""
    from src.integrity.failure_taxonomy import RunInvalidReason

    v2_required = {
        "mainnet_guard_triggered",
        "wallet_policy_rejected",
        "runtime_invocation_failed",
        "authorization_signature_rejected",
        "hosted_wallet_unavailable",
    }
    values = {m.value for m in RunInvalidReason}
    missing = v2_required - values
    assert not missing, f"Missing V2 RunInvalidReason values: {missing}"


# Test 4 ---------------------------------------------------------------


SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


def test_enum_values_are_lowercase_snake_case():
    """Every enum value is a lowercase_snake_case string."""
    from src.integrity.failure_taxonomy import RunInvalidReason, SagaFailureReason

    for member in list(SagaFailureReason) + list(RunInvalidReason):
        assert isinstance(member.value, str), (
            f"{member.name} value is not a str"
        )
        assert SNAKE_CASE.match(member.value), (
            f"{member.name} value {member.value!r} is not lowercase_snake_case"
        )


# Test 5 ---------------------------------------------------------------


def test_copy_map_covers_all_enum_members():
    """FAILURE_COPY_MAP has an entry for every SagaFailureReason + RunInvalidReason member."""
    from src.integrity.failure_taxonomy import RunInvalidReason, SagaFailureReason
    from src.integrity.failure_taxonomy_copy import FAILURE_COPY_MAP

    expected = set(SagaFailureReason) | set(RunInvalidReason)
    missing = expected - set(FAILURE_COPY_MAP.keys())
    assert not missing, f"FAILURE_COPY_MAP is missing entries for: {missing}"


# Test 6 ---------------------------------------------------------------


def test_copy_map_has_title_and_description():
    """Every FAILURE_COPY_MAP entry has a non-empty `title` and `description`."""
    from src.integrity.failure_taxonomy_copy import FAILURE_COPY_MAP

    for reason, copy in FAILURE_COPY_MAP.items():
        assert isinstance(copy, dict), f"{reason} copy is not a dict"
        assert "title" in copy and copy["title"], (
            f"{reason} missing non-empty title"
        )
        assert "description" in copy and copy["description"], (
            f"{reason} missing non-empty description"
        )


# Test 7 ---------------------------------------------------------------


def test_copy_map_has_no_orphan_entries():
    """FAILURE_COPY_MAP has no keys outside SagaFailureReason + RunInvalidReason."""
    from src.integrity.failure_taxonomy import RunInvalidReason, SagaFailureReason
    from src.integrity.failure_taxonomy_copy import FAILURE_COPY_MAP

    allowed = set(SagaFailureReason) | set(RunInvalidReason)
    orphans = set(FAILURE_COPY_MAP.keys()) - allowed
    assert not orphans, f"FAILURE_COPY_MAP has orphan entries: {orphans}"
