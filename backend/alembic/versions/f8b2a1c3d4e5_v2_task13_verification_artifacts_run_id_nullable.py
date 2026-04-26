"""v2_task13_verification_artifacts_run_id_nullable

Revision ID: f8b2a1c3d4e5
Revises: e2f5c9a4d1b8
Create Date: 2026-04-22

V2 Task 13 — deploy-time consent anchoring.

Deployment consent is anchored via the existing V1 ``VerificationArtifact``
primitive (V2_DESIGN_SPEC §10 invariant). At deploy time no ``Run`` exists
yet, so ``verification_artifacts.run_id`` must be nullable for
``artifact_type='deployment_consent'`` rows. The FK to ``runs.run_id`` is
retained for all V1 run-bound artifacts.

Forward-compatible: existing rows all have a non-null ``run_id`` and
satisfy the FK. The only new state is ``run_id IS NULL`` for deploy-time
consent artifacts inserted by ``InstanceService.deploy_instance``.

Downgrade restores NOT NULL; if any deploy-consent rows exist with NULL
``run_id``, the downgrade will fail — intentional, callers must purge or
migrate those rows first.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8b2a1c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e2f5c9a4d1b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("verification_artifacts") as batch:
        batch.alter_column(
            "run_id",
            existing_type=sa.BigInteger(),
            nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("verification_artifacts") as batch:
        batch.alter_column(
            "run_id",
            existing_type=sa.BigInteger(),
            nullable=False,
        )
