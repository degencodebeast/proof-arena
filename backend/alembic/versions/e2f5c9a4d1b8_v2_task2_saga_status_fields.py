"""v2_task2_saga_status_fields

Revision ID: e2f5c9a4d1b8
Revises: d7a412c8b3e9
Create Date: 2026-04-20

V2 Task 2 — extend ``agent_instances`` with saga lifecycle state fields.

Upgrade:
  1. Widen ``status`` from String(20) to String(32). Two of the seven saga
     enum values exceed 20 chars (``wallet_created_runtime_failed`` = 29,
     ``runtime_live_consent_failed`` = 27), so Postgres would reject them
     before the CHECK had a chance to validate. Widen BEFORE adding the CHECK.
  2. Add ``last_failure_reason`` (nullable String(64)). No backfill needed —
     it is a new nullable column; NULL is the correct initial state.
  3. Create ``idx_agent_instances_last_failure_reason`` for operator queries.
  4. Create CHECK on ``status`` (7-value saga enum).
  5. Create CHECK on ``last_failure_reason`` (NULL or SagaFailureReason value).

Downgrade:
  1. Drop the two CHECK constraints (last_failure_reason first — inverse
     of upgrade creation order).
  2. Drop the index.
  3. Drop the column.
  Column width is intentionally LEFT at String(32) — narrowing back to
  String(20) would reject any rows that Task 13's saga wrote with the
  longer saga-failure values. The pre-upgrade values (``provisioning``,
  ``live``, ``paused``, ``torn_down``) all still fit in the widened column,
  so this is functionally compatible with the pre-upgrade schema — just
  slightly more permissive.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e2f5c9a4d1b8"
down_revision: Union[str, Sequence[str], None] = "d7a412c8b3e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with SagaStatus / SagaFailureReason enums by the Task 2
# drift-guard tests in tests/test_task_2_saga_status.py.
_STATUS_VALUES = (
    "provisioning",
    "wallet_created_runtime_failed",
    "runtime_live_consent_failed",
    "provisioning_failed",
    "live",
    "paused",
    "torn_down",
)

_FAILURE_REASON_VALUES = (
    "provisioning_failed",
    "wallet_created_runtime_failed",
    "runtime_live_consent_failed",
)


def _in_list_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # 1. Widen status before the CHECK can see it.
    op.alter_column(
        "agent_instances",
        "status",
        existing_type=sa.String(20),
        type_=sa.String(32),
        existing_nullable=False,
    )

    # 2. Add last_failure_reason nullable column.
    op.add_column(
        "agent_instances",
        sa.Column("last_failure_reason", sa.String(64), nullable=True),
    )

    # 3. Index on last_failure_reason for operator queries.
    op.create_index(
        "idx_agent_instances_last_failure_reason",
        "agent_instances",
        ["last_failure_reason"],
    )

    # 4. CHECK on status (7 values).
    op.create_check_constraint(
        "ck_agent_instances_status",
        "agent_instances",
        f"status IN ({_in_list_sql(_STATUS_VALUES)})",
    )

    # 5. CHECK on last_failure_reason (NULL or one of the 3 SagaFailureReason values).
    op.create_check_constraint(
        "ck_agent_instances_last_failure_reason",
        "agent_instances",
        (
            "last_failure_reason IS NULL OR last_failure_reason IN ("
            + _in_list_sql(_FAILURE_REASON_VALUES)
            + ")"
        ),
    )


def downgrade() -> None:
    # Inverse of upgrade creation order: drop CHECKs first so the column
    # can be dropped cleanly.
    op.drop_constraint(
        "ck_agent_instances_last_failure_reason",
        "agent_instances",
        type_="check",
    )
    op.drop_constraint(
        "ck_agent_instances_status",
        "agent_instances",
        type_="check",
    )

    op.drop_index(
        "idx_agent_instances_last_failure_reason",
        table_name="agent_instances",
    )

    op.drop_column("agent_instances", "last_failure_reason")

    # Note: column width intentionally NOT narrowed back to String(20).
    # Rows Task 13's saga wrote with >20-char values would fail a narrow.
    # Pre-upgrade value set (provisioning | live | paused | torn_down) all
    # fit in String(32), so this is functionally compatible.
