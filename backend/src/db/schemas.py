"""Pydantic schemas — action types, status enums, and API request/response models.

This module is the single source of truth for:
- AgentAction schema (the normalized action contract)
- Lifecycle status enums (RunStatus, CompletionStatus, InvalidReason)
- Challenge status enum
- API request/response schemas
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Action schema (per VERSIONING.md: action_schema_version = agent_action_v1)
# ---------------------------------------------------------------------------


class AgentActionType(str, Enum):
    """The three allowed agent actions in V1."""

    EXECUTE_SWAP = "EXECUTE_SWAP"
    WAIT = "WAIT"
    FINISH = "FINISH"


class ExecuteSwapParams(BaseModel):
    """Parameters for EXECUTE_SWAP action."""

    model_config = ConfigDict(frozen=True)

    quote_id: str
    max_slippage_bps: int = Field(ge=0, le=500)


class WaitParams(BaseModel):
    """Parameters for WAIT action."""

    model_config = ConfigDict(frozen=True)

    seconds: int = Field(ge=1, le=60)


class FinishParams(BaseModel):
    """Parameters for FINISH action (empty)."""

    model_config = ConfigDict(frozen=True)


class AgentAction(BaseModel):
    """Normalized agent action — the contract between provider and runner."""

    model_config = ConfigDict(frozen=True)

    type: AgentActionType
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def validate_params(
        cls, v: dict[str, Any], info: Any
    ) -> dict[str, Any]:
        action_type = info.data.get("type")
        if action_type == AgentActionType.EXECUTE_SWAP:
            ExecuteSwapParams(**v)
        elif action_type == AgentActionType.WAIT:
            WaitParams(**v)
        elif action_type == AgentActionType.FINISH:
            if v:
                raise ValueError("FINISH action must have empty params")
        return v


# ---------------------------------------------------------------------------
# Lifecycle status enums
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    """Run lifecycle status — tracks execution progress."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class CompletionStatus(str, Enum):
    """Run completion validity — SEPARATE from lifecycle status.

    A run can be RunStatus.COMPLETED but CompletionStatus.INCOMPLETE
    (e.g., it finished execution but didn't complete the required basket).
    """

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"


class InvalidReason(str, Enum):
    """Explicit reasons why a run is invalid or incomplete."""

    INCOMPLETE_REQUIRED_ACTIONS = "incomplete_required_actions"
    INVALID_ACTION_ATTEMPTS_EXCEEDED = "invalid_action_attempts_exceeded"
    STALE_QUOTE_EXECUTION_FAILED = "stale_quote_execution_failed"
    TIMEOUT_BEFORE_COMPLETION = "timeout_before_completion"
    FLATTENING_FAILED = "flattening_failed"
    EXECUTION_ERROR = "execution_error"


class ChallengeStatus(str, Enum):
    """Challenge lifecycle status."""

    PENDING = "pending"
    ACTIVE = "active"
    SETTLING = "settling"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AgentStatus(str, Enum):
    """Agent status."""

    ACTIVE = "active"
    DISABLED = "disabled"


class ModerationStatus(str, Enum):
    """Admin moderation status."""

    PENDING = "pending"
    ACTIVE = "active"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Event type enum
# ---------------------------------------------------------------------------


class RunEventType(str, Enum):
    """Types of events in the run execution loop."""

    OBSERVE = "observe"
    DECIDE = "decide"
    VALIDATE = "validate"
    EXECUTE = "execute"
    ERROR = "error"
    FINISH = "finish"
    FLATTEN = "flatten"
    BUDGET_EXCEEDED = "budget_exceeded"
    FINALIZE = "finalize"
    ONCHAIN_FINALIZE = "onchain_finalize"  # Post-hash operational event


# ---------------------------------------------------------------------------
# API Request schemas
# ---------------------------------------------------------------------------


class StrategySubmitRequest(BaseModel):
    """Request to submit a new strategy."""

    agent_name: str = Field(max_length=64)
    system_prompt: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class ChallengeCreateRequest(BaseModel):
    """Request to create a new challenge (admin only)."""

    challenge_type: str = Field(default="swap_execution")
    starting_usdc: int = Field(gt=0, description="USDC in base units (6 decimals)")
    swap_intents: list[str] = Field(min_length=1)
    allowed_routes: list[list[str]] = Field(default_factory=list)
    max_slippage_bps: int = Field(default=100, ge=0, le=500)
    iteration_budget: int = Field(default=20, ge=1)
    time_budget_secs: int = Field(default=300, ge=30)
    llm_provider: str = Field(default="anthropic")
    llm_model: str = Field(default="claude-sonnet-4-20250514")
    contestant_agent_ids: list[int] = Field(min_length=1)


# ---------------------------------------------------------------------------
# API Response schemas
# ---------------------------------------------------------------------------


class StrategyResponse(BaseModel):
    """Response after submitting a strategy."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    display_name: str
    submission_hash: str
    onchain_address: str | None = None


class LeaderboardEntry(BaseModel):
    """One row on the leaderboard."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    display_name: str
    score: float
    rank_version: str
    wins: int
    losses: int
    completed_runs: int
    invalid_runs: int
    twitter_handle: str | None = None


class RunSummary(BaseModel):
    """Compact run summary for agent profiles."""

    model_config = ConfigDict(from_attributes=True)

    run_id: int
    challenge_id: int
    status: str
    completion_status: str | None = None
    starting_value: int
    ending_value: int | None = None


class RunEventSummary(BaseModel):
    """Summary of a single run event."""

    model_config = ConfigDict(from_attributes=True)

    event_id: int
    run_id: int
    sequence_no: int
    event_type: str
    timestamp: datetime
    tx_signature: str | None = None


class ContestantSummary(BaseModel):
    """Contestant info within a challenge."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    display_name: str
    run_id: int
    status: str
    completion_status: str | None = None
    ending_value: int | None = None


class ChallengeSummary(BaseModel):
    """Compact challenge for list views."""

    model_config = ConfigDict(from_attributes=True)

    challenge_id: int
    challenge_type: str
    challenge_version: str
    status: str
    num_contestants: int
    num_finalized: int
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ChallengeDetailResponse(BaseModel):
    """Full challenge detail."""

    model_config = ConfigDict(from_attributes=True)

    challenge_id: int
    challenge_type: str
    challenge_version: str
    llm_provider: str
    llm_model: str
    status: str
    config: dict[str, Any]
    num_contestants: int
    num_finalized: int
    winner_agent_id: int | None = None
    contestants: list[ContestantSummary] = Field(default_factory=list)
    created_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None


class AgentProfileResponse(BaseModel):
    """Full agent profile."""

    model_config = ConfigDict(from_attributes=True)

    agent_id: int
    display_name: str
    owner_wallet: str
    submission_hash: str
    twitter_handle: str | None = None
    current_rank: LeaderboardEntry | None = None
    recent_runs: list[RunSummary] = Field(default_factory=list)
    score_breakdown: dict[str, Any] = Field(default_factory=dict)


class RunDetailResponse(BaseModel):
    """Full run detail with events and evidence."""

    model_config = ConfigDict(from_attributes=True)

    run_id: int
    agent_id: int
    challenge_id: int
    status: str
    completion_status: str | None = None
    invalid_reason: str | None = None
    starting_value: int
    ending_value: int | None = None
    iterations_used: int = 0
    app_version: str
    challenge_type: str
    challenge_version: str
    action_schema_version: str
    evidence_schema_version: str
    events: list[RunEventSummary] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error response."""

    error_code: str
    message: str
    details: dict[str, Any] | None = None
