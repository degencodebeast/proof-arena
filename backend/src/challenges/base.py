"""ChallengeAdapter protocol — the interface for challenge types.

V1 implementation: SwapExecutionChallenge (fixed-basket swap execution).
V2 will add: YieldSprint, PredictionMarketTrading, PortfolioManagement, etc.

The adapter owns: initial state, available actions, completion criteria,
and score input computation for its challenge type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.db.models import Run


@dataclass
class ChallengeState:
    """Snapshot of a run's state within a challenge."""

    portfolio: dict[str, int]  # mint -> balance in base units
    completed_swaps: list[str]
    required_swaps: list[str]
    iterations_used: int
    elapsed_secs: float
    iteration_budget: int
    time_budget_secs: int
    status: str  # active, budget_exceeded, finished
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class QuoteOption:
    """A quote option presented to the agent for selection."""

    quote_id: str
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    fetched_at: str  # ISO 8601


@dataclass
class CompletionResult:
    """Result of evaluating whether a run meets completion criteria."""

    status: str  # complete, incomplete, invalid
    reason: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class ScoreInputs:
    """Raw inputs for rank computation, stored before any scoring formula."""

    completed_required_actions: bool
    completion_rate: float
    invalid_run: bool
    execution_quality: float  # ending_value / starting_value
    ending_value_delta: int  # ending - starting in base units
    iterations_used: int
    time_used_secs: float


@runtime_checkable
class ChallengeAdapter(Protocol):
    """Protocol for challenge type adapters."""

    async def build_initial_state(
        self, wallet_address: str
    ) -> ChallengeState:
        """Build the initial challenge state for a run."""
        ...

    async def list_available_actions(
        self, state: ChallengeState
    ) -> list[QuoteOption]:
        """List available quote options for the agent to choose from."""
        ...

    async def validate_completion(
        self, run: Run
    ) -> CompletionResult:
        """Check if a run meets the challenge completion criteria."""
        ...

    async def compute_score_inputs(
        self, run: Run
    ) -> ScoreInputs:
        """Compute raw score inputs from a completed run."""
        ...
