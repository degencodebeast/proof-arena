"""add_unique_challenge_agent_on_runs

Revision ID: 3ba44864cec7
Revises: bc7eaed1f30e
Create Date: 2026-04-14

Enforces one run per agent per challenge at the DB level.
Matches the on-chain PDA uniqueness: [b"run", challenge_id, agent_id].
"""

from typing import Sequence, Union

from alembic import op

revision: str = "3ba44864cec7"
down_revision: Union[str, Sequence[str], None] = "bc7eaed1f30e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_runs_challenge_agent",
        "runs",
        ["challenge_id", "agent_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_runs_challenge_agent", table_name="runs")
