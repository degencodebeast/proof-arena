"""v2_a4_subject_type_backfill_and_check

Revision ID: d7a412c8b3e9
Revises: c1e9a45b7d3f
Create Date: 2026-04-20

V2 Task A-4 — backfill ``agents.subject_type`` and
``rank_snapshots.subject_type`` to ``canonical_template`` for any
pre-existing rows, then add CHECK constraints on both columns enforcing
the two-value contract (``canonical_template`` | ``customized_instance``).
See ``src/integrity/subject_types.py``.

The column default was introduced in the V2 P0 migration
``7c4a2db90f15_v2_p0_templates_instances_subject_type``. This migration
defensively backfills any NULL/empty rows that may have been inserted
before that default was active, so the CHECK applies cleanly.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d7a412c8b3e9"
down_revision: Union[str, Sequence[str], None] = "c1e9a45b7d3f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Kept in sync with ``SubjectType`` enum by
# ``tests/test_task_a4_subject_type.py::test_models_subject_type_tuple_matches_enum``.
_ALLOWED = ("canonical_template", "customized_instance")


def _in_list_sql() -> str:
    return ", ".join(f"'{v}'" for v in _ALLOWED)


def upgrade() -> None:
    # Backfill any pre-P0 rows lacking the default value.
    op.execute(
        "UPDATE agents SET subject_type = 'canonical_template' "
        "WHERE subject_type IS NULL OR subject_type = ''"
    )
    op.execute(
        "UPDATE rank_snapshots SET subject_type = 'canonical_template' "
        "WHERE subject_type IS NULL OR subject_type = ''"
    )

    # Now enforce the two-value contract on both tables.
    op.create_check_constraint(
        "ck_agents_subject_type",
        "agents",
        f"subject_type IN ({_in_list_sql()})",
    )
    op.create_check_constraint(
        "ck_rank_snapshots_subject_type",
        "rank_snapshots",
        f"subject_type IN ({_in_list_sql()})",
    )


def downgrade() -> None:
    # Drop CHECKs first so the inverse UPDATEs are legal.
    op.drop_constraint(
        "ck_rank_snapshots_subject_type", "rank_snapshots", type_="check"
    )
    op.drop_constraint("ck_agents_subject_type", "agents", type_="check")

    # Revert the backfill. Note: we cannot distinguish rows backfilled by
    # ``upgrade()`` from rows legitimately written as ``canonical_template``
    # after upgrade. This nulls both kinds. That is the narrowest, most
    # deterministic downgrade available without persisting a marker at
    # upgrade time, and it matches the Task 7 contract that downgrade
    # revert the backfill.
    op.execute(
        "UPDATE rank_snapshots SET subject_type = NULL "
        "WHERE subject_type = 'canonical_template'"
    )
    op.execute(
        "UPDATE agents SET subject_type = NULL "
        "WHERE subject_type = 'canonical_template'"
    )
