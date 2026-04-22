"""v2_p0_templates_instances_subject_type

Revision ID: 7c4a2db90f15
Revises: 3ba44864cec7
Create Date: 2026-04-19

V2 Phase P0 — introduce the off-chain template + instance schema.

- agent_templates: canonical template catalog. Off-chain only per V2 spec
  §3 (zero new Anchor accounts for V2).
- agent_instances: private customized instances. Provider-agnostic field
  names so V0-VAL-1 outcomes can be recorded in `wallet_provider` and
  `hosted_wallet_ref` without a future migration.
- agents.subject_type: `canonical_template` vs `customized_instance`.
  All existing rows are backfilled to `canonical_template`.
- rank_snapshots.subject_type: same enum, backfilled the same way.

Reversible: downgrade drops the new columns/tables cleanly.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7c4a2db90f15"
down_revision: Union[str, Sequence[str], None] = "3ba44864cec7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # agent_templates
    op.create_table(
        "agent_templates",
        sa.Column("template_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("template_version", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("allowed_fields_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("default_config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column(
            "benchmark_subject_agent_id",
            sa.BigInteger(),
            sa.ForeignKey("agents.agent_id"),
            nullable=True,
        ),
        # `is_deployable` stored as int for SQLite/Postgres portability.
        sa.Column("is_deployable", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("template_key", name="uq_agent_templates_template_key"),
    )
    op.create_index(
        "idx_agent_templates_template_key",
        "agent_templates",
        ["template_key"],
    )

    # agent_instances
    op.create_table(
        "agent_instances",
        sa.Column("instance_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "template_id",
            sa.BigInteger(),
            sa.ForeignKey("agent_templates.template_id"),
            nullable=False,
        ),
        sa.Column("template_version_at_deploy", sa.String(32), nullable=False),
        sa.Column("instance_owner_ref", sa.String(128), nullable=False),
        sa.Column("effective_config_json", sa.Text(), nullable=False),
        sa.Column(
            "consent_artifact_id",
            sa.BigInteger(),
            sa.ForeignKey("verification_artifacts.artifact_id"),
            nullable=True,
        ),
        sa.Column("runtime_handle_json", sa.Text(), nullable=True),
        sa.Column("wallet_address", sa.String(44), nullable=True),
        sa.Column("hosted_wallet_ref", sa.String(128), nullable=True),
        sa.Column("wallet_provider", sa.String(32), nullable=True),
        sa.Column(
            "trust_label",
            sa.String(64),
            nullable=False,
            server_default="benchmark_compatible_customized_instance",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="provisioning",
        ),
        sa.Column(
            "superseded_by_instance_id",
            sa.BigInteger(),
            sa.ForeignKey("agent_instances.instance_id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_agent_instances_template_id", "agent_instances", ["template_id"]
    )
    op.create_index(
        "idx_agent_instances_owner", "agent_instances", ["instance_owner_ref"]
    )
    op.create_index(
        "idx_agent_instances_status", "agent_instances", ["status"]
    )

    # agents.subject_type — add with default + backfill existing rows atomically.
    op.add_column(
        "agents",
        sa.Column(
            "subject_type",
            sa.String(32),
            nullable=False,
            server_default="canonical_template",
        ),
    )
    # Explicit backfill; server_default covers inserts, but we want the
    # invariant to show up as a real row state in any backfilled audit.
    op.execute(
        "UPDATE agents SET subject_type = 'canonical_template' WHERE subject_type IS NULL"
    )
    op.create_index("idx_agents_subject_type", "agents", ["subject_type"])

    # rank_snapshots.subject_type — same pattern.
    op.add_column(
        "rank_snapshots",
        sa.Column(
            "subject_type",
            sa.String(32),
            nullable=False,
            server_default="canonical_template",
        ),
    )
    op.execute(
        "UPDATE rank_snapshots SET subject_type = 'canonical_template' "
        "WHERE subject_type IS NULL"
    )
    op.create_index(
        "idx_rank_snapshots_subject_type", "rank_snapshots", ["subject_type"]
    )


def downgrade() -> None:
    # Undo in strict reverse order.
    op.drop_index("idx_rank_snapshots_subject_type", table_name="rank_snapshots")
    op.drop_column("rank_snapshots", "subject_type")

    op.drop_index("idx_agents_subject_type", table_name="agents")
    op.drop_column("agents", "subject_type")

    op.drop_index("idx_agent_instances_status", table_name="agent_instances")
    op.drop_index("idx_agent_instances_owner", table_name="agent_instances")
    op.drop_index("idx_agent_instances_template_id", table_name="agent_instances")
    op.drop_table("agent_instances")

    op.drop_index("idx_agent_templates_template_key", table_name="agent_templates")
    op.drop_table("agent_templates")
