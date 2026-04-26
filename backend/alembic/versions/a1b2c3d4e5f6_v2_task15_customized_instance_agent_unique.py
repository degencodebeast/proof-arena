"""v2_task15_customized_instance_agent_unique

Revision ID: a1b2c3d4e5f6
Revises: f8b2a1c3d4e5
Create Date: 2026-04-22

V2 Task 15 follow-up — concurrency-safe instance→agent dedupe.

``ChallengeService._get_or_create_instance_agent`` uses the synthetic
key ``privy_user_id = "instance:{instance_id}"`` to map a hosted
``AgentInstance`` to its ``Agent`` row. The read-then-insert pattern
is not race-safe unless the DB refuses duplicate keys. Enforce via a
partial unique index scoped to ``subject_type = 'customized_instance'``:

- AT MOST ONE customized_instance agent row per synthetic key.
- V1 N-per-user semantics on canonical_template rows (per
  ``strategy_service.get_by_owner`` + ``get_active_count``) are
  preserved — the index only applies to customized_instance rows.

Reversible via index drop.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f8b2a1c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = "uq_agents_privy_user_id_customized_instance"
_PREDICATE = "subject_type = 'customized_instance'"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "agents",
        ["privy_user_id"],
        unique=True,
        postgresql_where=sa.text(_PREDICATE),
        sqlite_where=sa.text(_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="agents")
