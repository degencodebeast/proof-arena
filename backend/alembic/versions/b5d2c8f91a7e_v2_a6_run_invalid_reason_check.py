"""v2_a6_run_invalid_reason_check

Revision ID: b5d2c8f91a7e
Revises: 7c4a2db90f15
Create Date: 2026-04-20

V2 Task A-6 — add a CHECK constraint on ``runs.invalid_reason`` so every
recorded value must be a member of the authoritative ``RunInvalidReason``
enum (see ``src/integrity/failure_taxonomy.py``). Backfill any pre-existing
off-contract values to NULL first so the constraint applies cleanly.

Scope is intentionally narrow: ``agent_instances.last_failure_reason`` +
status expansion + their CHECKs are owned by Task 2, which adds the
``last_failure_reason`` column.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "b5d2c8f91a7e"
down_revision: Union[str, Sequence[str], None] = "7c4a2db90f15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with ``RunInvalidReason`` enum by
# ``tests/test_task_a6_failure_taxonomy.py::test_run_invalid_reason_check_sql_matches_enum``.
_ALLOWED = (
    # V1 preserved
    "incomplete_required_actions",
    "invalid_action_attempts_exceeded",
    "stale_quote_execution_failed",
    "timeout_before_completion",
    "flattening_failed",
    "execution_error",
    # V2 additions
    "mainnet_guard_triggered",
    "wallet_policy_rejected",
    "runtime_invocation_failed",
    "authorization_signature_rejected",
    "hosted_wallet_unavailable",
)


def _in_list_sql() -> str:
    return ", ".join(f"'{v}'" for v in _ALLOWED)


def upgrade() -> None:
    # Backfill: any pre-existing off-contract value was already
    # data-corruption; null it out so the CHECK applies cleanly.
    op.execute(
        "UPDATE runs SET invalid_reason = NULL "
        "WHERE invalid_reason IS NOT NULL "
        f"AND invalid_reason NOT IN ({_in_list_sql()})"
    )
    op.create_check_constraint(
        "ck_runs_invalid_reason",
        "runs",
        f"invalid_reason IS NULL OR invalid_reason IN ({_in_list_sql()})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_runs_invalid_reason", "runs", type_="check")
