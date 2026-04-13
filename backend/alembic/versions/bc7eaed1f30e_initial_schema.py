"""initial_schema

Revision ID: bc7eaed1f30e
Revises:
Create Date: 2026-04-12

Creates all 6 tables: agents, challenges, runs, run_events,
rank_snapshots, verification_artifacts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "bc7eaed1f30e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- agents ---
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("privy_user_id", sa.String(128), nullable=False),
        sa.Column("owner_wallet", sa.String(44), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("submission_type", sa.String(32), nullable=False, server_default="local"),
        sa.Column("submission_hash", sa.String(64), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("metadata_ref", sa.String(256), nullable=True),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="local"),
        sa.Column("provider_config_json", sa.Text(), nullable=True),
        sa.Column("twitter_handle", sa.String(64), nullable=True),
        sa.Column("onchain_address", sa.String(44), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("moderation_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_agents_privy_user_id", "agents", ["privy_user_id"])
    op.create_index("idx_agents_owner_wallet", "agents", ["owner_wallet"])

    # --- challenges ---
    op.create_table(
        "challenges",
        sa.Column("challenge_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("challenge_type", sa.String(32), nullable=False, server_default="swap_execution"),
        sa.Column("challenge_version", sa.String(32), nullable=False, server_default="swap_execution_v1"),
        sa.Column("llm_provider", sa.String(32), nullable=False),
        sa.Column("llm_model", sa.String(64), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("instance_seed", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("num_contestants", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("num_finalized", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winner_agent_id", sa.BigInteger(), nullable=True),
        sa.Column("onchain_address", sa.String(44), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_challenges_status", "challenges", ["status"])

    # --- runs ---
    op.create_table(
        "runs",
        sa.Column("run_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("challenge_id", sa.BigInteger(), sa.ForeignKey("challenges.challenge_id"), nullable=False),
        sa.Column("agent_id", sa.BigInteger(), sa.ForeignKey("agents.agent_id"), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False, server_default="local"),
        sa.Column("benchmark_wallet_address", sa.String(44), nullable=True),
        sa.Column("benchmark_wallet_ref", sa.String(128), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("completion_status", sa.String(20), nullable=True),
        sa.Column("invalid_reason", sa.String(64), nullable=True),
        sa.Column("starting_value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("ending_value", sa.BigInteger(), nullable=True),
        sa.Column("iterations_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score_inputs_json", sa.Text(), nullable=True),
        sa.Column("run_log_hash", sa.String(64), nullable=True),
        sa.Column("app_version", sa.String(16), nullable=False, server_default="0.1.0"),
        sa.Column("challenge_type", sa.String(32), nullable=False, server_default="swap_execution"),
        sa.Column("challenge_version", sa.String(32), nullable=False, server_default="swap_execution_v1"),
        sa.Column("action_schema_version", sa.String(32), nullable=False, server_default="agent_action_v1"),
        sa.Column("evidence_schema_version", sa.String(32), nullable=False, server_default="evidence_v1"),
        sa.Column("onchain_address", sa.String(44), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_runs_challenge_id", "runs", ["challenge_id"])
    op.create_index("idx_runs_agent_id", "runs", ["agent_id"])
    op.create_index("idx_runs_status", "runs", ["status"])

    # --- run_events ---
    op.create_table(
        "run_events",
        sa.Column("event_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("state_snapshot_json", sa.Text(), nullable=True),
        sa.Column("action_payload_json", sa.Text(), nullable=True),
        sa.Column("validation_payload_json", sa.Text(), nullable=True),
        sa.Column("execution_payload_json", sa.Text(), nullable=True),
        sa.Column("result_payload_json", sa.Text(), nullable=True),
        sa.Column("tx_signature", sa.String(88), nullable=True),
        sa.Column("quote_snapshot_ref", sa.Text(), nullable=True),
    )
    op.create_index("idx_run_events_run_id", "run_events", ["run_id"])
    op.create_index("idx_run_events_run_sequence", "run_events", ["run_id", "sequence_no"], unique=True)

    # --- rank_snapshots ---
    op.create_table(
        "rank_snapshots",
        sa.Column("snapshot_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("agent_id", sa.BigInteger(), sa.ForeignKey("agents.agent_id"), nullable=False),
        sa.Column("rank_version", sa.String(32), nullable=False, server_default="rank_v1"),
        sa.Column("app_version", sa.String(16), nullable=False, server_default="0.1.0"),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("score_inputs_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("score_breakdown_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("wins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_rank_snapshots_agent_id", "rank_snapshots", ["agent_id"])
    op.create_index("idx_rank_snapshots_computed_at", "rank_snapshots", ["computed_at"])

    # --- verification_artifacts ---
    op.create_table(
        "verification_artifacts",
        sa.Column("artifact_id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("runs.run_id"), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("uri_or_ref", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_verification_artifacts_run_id", "verification_artifacts", ["run_id"])


def downgrade() -> None:
    op.drop_table("verification_artifacts")
    op.drop_table("rank_snapshots")
    op.drop_table("run_events")
    op.drop_table("runs")
    op.drop_table("challenges")
    op.drop_table("agents")
