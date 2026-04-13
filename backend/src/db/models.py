"""SQLAlchemy 2.0 ORM models — the canonical off-chain data contracts.

Field lists match the implementation plan Section 5 exactly.
All version fields required by VERSIONING.md are present.
Run.status (lifecycle) and Run.completion_status (validity) are SEPARATE.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


# ---------------------------------------------------------------------------
# Agent (agents table)
# ---------------------------------------------------------------------------


class Agent(Base):
    __tablename__ = "agents"

    agent_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    privy_user_id: Mapped[str] = mapped_column(String(128), index=True)
    owner_wallet: Mapped[str] = mapped_column(String(44))
    display_name: Mapped[str] = mapped_column(String(64))
    submission_type: Mapped[str] = mapped_column(
        String(32), default="local"
    )
    submission_hash: Mapped[str] = mapped_column(String(64))
    system_prompt: Mapped[str] = mapped_column(Text)
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    metadata_ref: Mapped[Optional[str]] = mapped_column(String(256))
    provider_type: Mapped[str] = mapped_column(
        String(32), default="local"
    )
    provider_config_json: Mapped[Optional[str]] = mapped_column(Text)
    twitter_handle: Mapped[Optional[str]] = mapped_column(String(64))
    onchain_address: Mapped[Optional[str]] = mapped_column(String(44))
    status: Mapped[str] = mapped_column(String(20), default="active")
    moderation_status: Mapped[str] = mapped_column(
        String(20), default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    runs: Mapped[list["Run"]] = relationship(back_populates="agent")
    rank_snapshots: Mapped[list["RankSnapshot"]] = relationship(
        back_populates="agent"
    )

    __table_args__ = (
        Index("idx_agents_privy_user_id", "privy_user_id"),
        Index("idx_agents_owner_wallet", "owner_wallet"),
    )


# ---------------------------------------------------------------------------
# Challenge (challenges table)
# ---------------------------------------------------------------------------


class Challenge(Base):
    __tablename__ = "challenges"

    challenge_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    challenge_type: Mapped[str] = mapped_column(
        String(32), default="swap_execution"
    )
    challenge_version: Mapped[str] = mapped_column(
        String(32), default="swap_execution_v1"
    )
    llm_provider: Mapped[str] = mapped_column(String(32))
    llm_model: Mapped[str] = mapped_column(String(64))
    config_json: Mapped[str] = mapped_column(Text)
    instance_seed: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    num_contestants: Mapped[int] = mapped_column(Integer, default=0)
    num_finalized: Mapped[int] = mapped_column(Integer, default=0)
    winner_agent_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    onchain_address: Mapped[Optional[str]] = mapped_column(String(44))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Relationships
    runs: Mapped[list["Run"]] = relationship(back_populates="challenge")

    __table_args__ = (
        Index("idx_challenges_status", "status"),
    )


# ---------------------------------------------------------------------------
# Run (runs table)
# CRITICAL: status (lifecycle) and completion_status (validity) are SEPARATE.
# ---------------------------------------------------------------------------


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    challenge_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("challenges.challenge_id"), index=True
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.agent_id"), index=True
    )
    provider_type: Mapped[str] = mapped_column(
        String(32), default="local"
    )
    benchmark_wallet_address: Mapped[Optional[str]] = mapped_column(
        String(44)
    )
    benchmark_wallet_ref: Mapped[Optional[str]] = mapped_column(
        String(128)
    )
    # Lifecycle status: pending, running, completed, failed, timeout
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Completion validity: complete, incomplete, invalid (SEPARATE from status)
    completion_status: Mapped[Optional[str]] = mapped_column(String(20))
    # Explicit reason if invalid or incomplete
    invalid_reason: Mapped[Optional[str]] = mapped_column(String(64))
    starting_value: Mapped[int] = mapped_column(BigInteger, default=0)
    ending_value: Mapped[Optional[int]] = mapped_column(BigInteger)
    iterations_used: Mapped[int] = mapped_column(Integer, default=0)
    score_inputs_json: Mapped[Optional[str]] = mapped_column(Text)
    run_log_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # Version fields per VERSIONING.md — every Run must persist all of these
    app_version: Mapped[str] = mapped_column(String(16), default="0.1.0")
    challenge_type: Mapped[str] = mapped_column(
        String(32), default="swap_execution"
    )
    challenge_version: Mapped[str] = mapped_column(
        String(32), default="swap_execution_v1"
    )
    action_schema_version: Mapped[str] = mapped_column(
        String(32), default="agent_action_v1"
    )
    evidence_schema_version: Mapped[str] = mapped_column(
        String(32), default="evidence_v1"
    )
    onchain_address: Mapped[Optional[str]] = mapped_column(String(44))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Relationships
    challenge: Mapped["Challenge"] = relationship(back_populates="runs")
    agent: Mapped["Agent"] = relationship(back_populates="runs")
    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", order_by="RunEvent.sequence_no"
    )
    verification_artifacts: Mapped[list["VerificationArtifact"]] = (
        relationship(back_populates="run")
    )

    __table_args__ = (
        Index("idx_runs_challenge_id", "challenge_id"),
        Index("idx_runs_agent_id", "agent_id"),
        Index("idx_runs_status", "status"),
    )


# ---------------------------------------------------------------------------
# RunEvent (run_events table)
# ---------------------------------------------------------------------------


class RunEvent(Base):
    __tablename__ = "run_events"

    event_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.run_id"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(32))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    state_snapshot_json: Mapped[Optional[str]] = mapped_column(Text)
    action_payload_json: Mapped[Optional[str]] = mapped_column(Text)
    validation_payload_json: Mapped[Optional[str]] = mapped_column(Text)
    execution_payload_json: Mapped[Optional[str]] = mapped_column(Text)
    result_payload_json: Mapped[Optional[str]] = mapped_column(Text)
    tx_signature: Mapped[Optional[str]] = mapped_column(String(88))
    quote_snapshot_ref: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    run: Mapped["Run"] = relationship(back_populates="events")

    __table_args__ = (
        Index("idx_run_events_run_id", "run_id"),
        Index(
            "idx_run_events_run_sequence",
            "run_id",
            "sequence_no",
            unique=True,
        ),
    )


# ---------------------------------------------------------------------------
# RankSnapshot (rank_snapshots table) — append-only, never overwrite
# ---------------------------------------------------------------------------


class RankSnapshot(Base):
    __tablename__ = "rank_snapshots"

    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agents.agent_id"), index=True
    )
    rank_version: Mapped[str] = mapped_column(
        String(32), default="rank_v1"
    )
    app_version: Mapped[str] = mapped_column(
        String(16), default="0.1.0"
    )
    score: Mapped[float] = mapped_column(Float, default=0.0)
    score_inputs_json: Mapped[str] = mapped_column(Text, default="{}")
    score_breakdown_json: Mapped[str] = mapped_column(Text, default="{}")
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    completed_runs: Mapped[int] = mapped_column(Integer, default=0)
    invalid_runs: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="rank_snapshots")

    __table_args__ = (
        Index("idx_rank_snapshots_agent_id", "agent_id"),
        Index("idx_rank_snapshots_computed_at", "computed_at"),
    )


# ---------------------------------------------------------------------------
# VerificationArtifact (verification_artifacts table)
# ---------------------------------------------------------------------------


class VerificationArtifact(Base):
    __tablename__ = "verification_artifacts"

    artifact_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("runs.run_id"), index=True
    )
    artifact_type: Mapped[str] = mapped_column(String(32))
    uri_or_ref: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    run: Mapped["Run"] = relationship(
        back_populates="verification_artifacts"
    )

    __table_args__ = (
        Index("idx_verification_artifacts_run_id", "run_id"),
    )
