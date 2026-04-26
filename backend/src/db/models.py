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
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# V2 A-6 — CHECK-list for runs.invalid_reason.
#
# The authoritative enum lives in src/integrity/failure_taxonomy.py
# (``RunInvalidReason``). We do NOT import it here because the integrity
# package's ``__init__`` eagerly imports modules that back-reference
# ``src.db.models`` (circular import). The A-6 test
# ``test_run_invalid_reason_check_sql_matches_enum`` asserts this list stays
# byte-equal to the enum; any drift fails fast. Do not edit in isolation —
# update both the enum and this tuple atomically.
_RUN_INVALID_REASON_VALUES: tuple[str, ...] = (
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

_RUN_INVALID_REASON_CHECK_SQL = (
    "invalid_reason IS NULL OR invalid_reason IN ("
    + ", ".join(f"'{v}'" for v in _RUN_INVALID_REASON_VALUES)
    + ")"
)

# V2 A-5 — CHECK-list for agent_instances.trust_label.
#
# The authoritative enum lives in src/integrity/trust_labels.py
# (``TrustLabel``). We do NOT import it here for the same reason as
# _RUN_INVALID_REASON_VALUES above: the integrity package's ``__init__``
# eagerly imports modules that back-reference ``src.db.models``. The A-5
# test ``test_models_trust_label_tuple_matches_enum`` asserts this tuple
# stays byte-equal to the enum; any drift fails fast.
_TRUST_LABEL_VALUES: tuple[str, ...] = (
    "benchmarked_canonical_template",
    "benchmark_compatible_customized_instance",
    "external_custom_runtime",
)

_TRUST_LABEL_CHECK_SQL = (
    "trust_label IN ("
    + ", ".join(f"'{v}'" for v in _TRUST_LABEL_VALUES)
    + ")"
)

# V2 A-4 — CHECK-list for agents.subject_type and rank_snapshots.subject_type.
#
# The authoritative enum lives in src/integrity/subject_types.py
# (``SubjectType``). Duplicated here to avoid the circular import with
# ``src.integrity``; the A-4 drift-guard test
# ``test_models_subject_type_tuple_matches_enum`` asserts byte-equality.
_SUBJECT_TYPE_VALUES: tuple[str, ...] = (
    "canonical_template",
    "customized_instance",
)

_SUBJECT_TYPE_CHECK_SQL = (
    "subject_type IN ("
    + ", ".join(f"'{v}'" for v in _SUBJECT_TYPE_VALUES)
    + ")"
)

# V2 Task 2 — CHECK-lists for agent_instances.status and
# agent_instances.last_failure_reason.
#
# Authoritative enums live at:
#   - src/integrity/saga_statuses.py  (``SagaStatus``)
#   - src/integrity/failure_taxonomy.py  (``SagaFailureReason``)
# Duplicated here to avoid circular import via the integrity package init.
# Drift-guard tests (task_2) hold both tuples byte-equal to their enums.
_SAGA_STATUS_VALUES: tuple[str, ...] = (
    "provisioning",
    "wallet_created_runtime_failed",
    "runtime_live_consent_failed",
    "provisioning_failed",
    "live",
    "paused",
    "torn_down",
)

_SAGA_STATUS_CHECK_SQL = (
    "status IN ("
    + ", ".join(f"'{v}'" for v in _SAGA_STATUS_VALUES)
    + ")"
)

_SAGA_FAILURE_REASON_VALUES: tuple[str, ...] = (
    "provisioning_failed",
    "wallet_created_runtime_failed",
    "runtime_live_consent_failed",
)

_SAGA_FAILURE_REASON_CHECK_SQL = (
    "last_failure_reason IS NULL OR last_failure_reason IN ("
    + ", ".join(f"'{v}'" for v in _SAGA_FAILURE_REASON_VALUES)
    + ")"
)


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
    # V2 P0: subject-typed reputation. `canonical_template` for V1-origin rows
    # and flagship agents; `customized_instance` for V2 user-deployed instances.
    # Backfilled to `canonical_template` on migration.
    subject_type: Mapped[str] = mapped_column(
        String(32), default="canonical_template"
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
        Index("idx_agents_subject_type", "subject_type"),
        # V2 Task 15: partial unique index on privy_user_id scoped to
        # customized_instance rows. Enforces DB-level dedupe of the
        # synthetic `instance:{id}` key used by ChallengeService's
        # instance→agent mapping, while preserving V1's N-per-user
        # semantics for canonical_template rows (see strategy_service
        # get_by_owner / get_active_count). Matches Alembic migration
        # a1b2c3d4e5f6.
        Index(
            "uq_agents_privy_user_id_customized_instance",
            "privy_user_id",
            unique=True,
            sqlite_where=text("subject_type = 'customized_instance'"),
            postgresql_where=text("subject_type = 'customized_instance'"),
        ),
        # V2 A-4: subject_type must be one of the two locked values.
        CheckConstraint(
            _SUBJECT_TYPE_CHECK_SQL,
            name="ck_agents_subject_type",
        ),
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
        Index("uq_runs_challenge_agent", "challenge_id", "agent_id", unique=True),
        # V2 A-6: invalid_reason must be NULL or one of RunInvalidReason.
        CheckConstraint(
            _RUN_INVALID_REASON_CHECK_SQL,
            name="ck_runs_invalid_reason",
        ),
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
    # V2 P0: subject-typed reputation. Aggregate leaderboards MUST filter on
    # this so canonical-template and customized-instance ranks never blend.
    subject_type: Mapped[str] = mapped_column(
        String(32), default="canonical_template"
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="rank_snapshots")

    __table_args__ = (
        Index("idx_rank_snapshots_agent_id", "agent_id"),
        Index("idx_rank_snapshots_computed_at", "computed_at"),
        Index("idx_rank_snapshots_subject_type", "subject_type"),
        # V2 A-4: subject_type must be one of the two locked values —
        # same contract as agents.subject_type.
        CheckConstraint(
            _SUBJECT_TYPE_CHECK_SQL,
            name="ck_rank_snapshots_subject_type",
        ),
    )


# ---------------------------------------------------------------------------
# VerificationArtifact (verification_artifacts table)
# ---------------------------------------------------------------------------


class VerificationArtifact(Base):
    __tablename__ = "verification_artifacts"

    artifact_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    # Nullable for V2 deployment-consent artifacts (no run exists at deploy
    # time). V1 run-bound artifacts still populate this with a valid
    # runs.run_id; the FK itself is unchanged. See Alembic migration
    # f8b2a1c3d4e5 (Task 13).
    run_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("runs.run_id"), index=True, nullable=True
    )
    artifact_type: Mapped[str] = mapped_column(String(32))
    uri_or_ref: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships — Optional[Run] because V2 deploy-consent artifacts
    # have NULL run_id (see Task 13).
    run: Mapped[Optional["Run"]] = relationship(
        back_populates="verification_artifacts"
    )

    __table_args__ = (
        Index("idx_verification_artifacts_run_id", "run_id"),
    )


# ---------------------------------------------------------------------------
# V2 P0: AgentTemplate (agent_templates table)
# Off-chain only. No on-chain representation in V2 (see V2_DESIGN_SPEC §3
# "Anchor state and instructions" — zero new Anchor accounts for V2).
# ---------------------------------------------------------------------------


class AgentTemplate(Base):
    __tablename__ = "agent_templates"

    template_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    template_key: Mapped[str] = mapped_column(
        String(64), unique=True, index=True
    )
    # Symbolic version label per VERSIONING.md (e.g. "swap_executor_v1").
    template_version: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    # JSON-encoded list of allowed envelope field names (the V2 5-field set).
    allowed_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    default_config_json: Mapped[str] = mapped_column(Text, default="{}")
    system_prompt: Mapped[str] = mapped_column(Text)
    benchmark_subject_agent_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("agents.agent_id")
    )
    is_deployable: Mapped[bool] = mapped_column(
        Integer, default=1
    )  # use Integer for SQLite/Postgres portability; 0/1 semantics
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_agent_templates_template_key", "template_key"),
    )


# ---------------------------------------------------------------------------
# V2 P0: AgentInstance (agent_instances table)
# Private by default. Consent artifact FK populated at deploy time (Phase B
# orchestration). Provider-agnostic field names — the Privy-specific shape
# is encoded inside `hosted_wallet_ref` / `wallet_provider` values, not in
# the column names, so V0-VAL-1 outcomes can be recorded here without a
# schema change.
# ---------------------------------------------------------------------------


class AgentInstance(Base):
    __tablename__ = "agent_instances"

    instance_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    template_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("agent_templates.template_id"), index=True
    )
    template_version_at_deploy: Mapped[str] = mapped_column(String(32))
    # V2 auth-provider-specific owner identifier; shape depends on V0-VAL-1.
    instance_owner_ref: Mapped[str] = mapped_column(String(128), index=True)
    # Envelope-validated effective config.
    effective_config_json: Mapped[str] = mapped_column(Text)
    # FK into verification_artifacts. Populated at deploy time (Phase B).
    # Nullable at the column level for now: P0 doesn't run deployments, and
    # a NOT NULL constraint would make Phase B forced to two-phase commit
    # the instance row and the consent artifact. Keeping nullable preserves
    # atomic single-transaction inserts; Phase B enforces non-null in the
    # service layer.
    consent_artifact_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("verification_artifacts.artifact_id")
    )
    # Opaque runtime-specific handle. Never surfaced publicly.
    runtime_handle_json: Mapped[Optional[str]] = mapped_column(Text)
    # Chain-level address, provider-agnostic.
    wallet_address: Mapped[Optional[str]] = mapped_column(String(44))
    # Wallet-provider-specific identifier (e.g. a Privy wallet ID if
    # V0-VAL-1 locks Privy). Schema stays provider-agnostic so a later
    # swap doesn't require a migration.
    hosted_wallet_ref: Mapped[Optional[str]] = mapped_column(String(128))
    wallet_provider: Mapped[Optional[str]] = mapped_column(String(32))
    # Trust label per V2 spec §3 and the Task 6 / A-5 contract
    # (see src/integrity/trust_labels.py + ck_agent_instances_trust_label):
    # `benchmarked_canonical_template` (flagship instance only)
    #   | `benchmark_compatible_customized_instance` (default for user deploys)
    #   | `external_custom_runtime` (reserved in V2; no code path assigns it)
    trust_label: Mapped[str] = mapped_column(
        String(64), default="benchmark_compatible_customized_instance"
    )
    # V2 Task 2: saga lifecycle state machine (7 states).
    #   provisioning  -> (wallet_created_runtime_failed | runtime_live_consent_failed
    #                     | provisioning_failed | live)
    #   live          -> (paused | torn_down)
    #   paused        -> (live | torn_down)
    #   torn_down     -> (terminal)
    # Column widened from String(20) to String(32) to fit the two saga-failure
    # values (both > 20 chars). CHECK constraint pinned by _SAGA_STATUS_VALUES.
    status: Mapped[str] = mapped_column(String(32), default="provisioning")
    # V2 Task 2: operator-surface failure reason. Populated only when status
    # is one of the three *_failed saga states. Allowed values come from
    # SagaFailureReason in src/integrity/failure_taxonomy.py.
    last_failure_reason: Mapped[Optional[str]] = mapped_column(String(64))
    # Self-referential nullable FK for instance versioning.
    superseded_by_instance_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("agent_instances.instance_id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_agent_instances_template_id", "template_id"),
        Index("idx_agent_instances_owner", "instance_owner_ref"),
        Index("idx_agent_instances_status", "status"),
        Index(
            "idx_agent_instances_last_failure_reason",
            "last_failure_reason",
        ),
        # V2 A-5: trust_label must be one of the three locked values.
        CheckConstraint(
            _TRUST_LABEL_CHECK_SQL,
            name="ck_agent_instances_trust_label",
        ),
        # V2 Task 2: status must be one of the seven saga-state values.
        CheckConstraint(
            _SAGA_STATUS_CHECK_SQL,
            name="ck_agent_instances_status",
        ),
        # V2 Task 2: last_failure_reason is NULL or a SagaFailureReason value.
        CheckConstraint(
            _SAGA_FAILURE_REASON_CHECK_SQL,
            name="ck_agent_instances_last_failure_reason",
        ),
    )
