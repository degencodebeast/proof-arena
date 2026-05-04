"""RebalanceExecutionChallenge — V0 dry-run / decision-only adapter.

V0 scope (spec §5.4 locked phrasing):
- Decision-only, not generalized tool-calling.
- Agent emits FINISH; the platform computes the deterministic rebalance plan.
- No live multi-leg execution.
- emit_run_evidence writes one rebalance_evidence_v1 VerificationArtifact at finalize.

Spec §5.5: canonical evidence JSON is stored inline in VerificationArtifact.uri_or_ref.
"""
from __future__ import annotations

from typing import Any

from src.challenges.base import (
    ChallengeState,
    CompletionResult,
    QuoteOption,
    ScoreInputs,
)
from src.db.schemas import AgentActionType


class RebalanceExecutionChallenge:
    """V0 rebalance adapter. tools=[] decision-only on the agent side."""

    def __init__(self, config: dict[str, Any]):
        self.allowed_token_universe: list[str] = list(
            config.get("allowed_token_universe", [])
        )
        self.target_allocations: dict[str, float] = dict(
            config.get("target_allocations", {})
        )
        self.rebalance_threshold_bps: int = int(config.get("rebalance_threshold_bps", 50))
        self.max_slippage_bps: int = int(config.get("max_slippage_bps", 100))
        self.max_position_weight: float = float(config.get("max_position_weight", 0.7))
        self.max_trade_value: int = int(config.get("max_trade_value", 1_000_000_000))
        self.dry_run: bool = bool(config.get("dry_run", True))
        self.starting_value: int = int(config.get("starting_usdc", 0))
        # Iteration / time budget reuse swap defaults so the runner loop terminates
        # promptly even if the agent emits WAIT before FINISH.
        self.iteration_budget: int = int(config.get("iteration_budget", 5))
        self.time_budget_secs: int = int(config.get("time_budget_secs", 60))

    # ----- ChallengeAdapter base contract (same shape as swap) -----

    async def build_initial_state(self, wallet_address: str) -> ChallengeState:
        return ChallengeState(
            portfolio={},
            completed_swaps=[],
            required_swaps=[],   # rebalance V0 has no swap-intent list
            iterations_used=0,
            elapsed_secs=0.0,
            iteration_budget=self.iteration_budget,
            time_budget_secs=self.time_budget_secs,
            status="active",
            extra={
                "wallet_address": wallet_address,
                "template_key": "rebalance_executor_v1",
                "dry_run": self.dry_run,
            },
        )

    async def list_available_actions(self, state: ChallengeState) -> list[QuoteOption]:
        # Decision-only: no quote shopping is exposed to the agent in V0.
        return []

    async def validate_completion(
        self, run_events: list[dict], final_balances: dict[str, int]
    ) -> CompletionResult:
        """V0 dry-run: a FINISH-emitted run is always 'complete' at the runner layer.

        The Cat layer (Task 19) is the trust evaluator that may report fail.
        """
        for event in run_events:
            if event.get("event_type") == "finish":
                return CompletionResult(status="complete")
        return CompletionResult(
            status="incomplete",
            reason="incomplete_required_actions",
            details={"hint": "rebalance V0 requires the agent to emit FINISH"},
        )

    async def compute_score_inputs(
        self,
        starting_value: int,
        ending_value: int,
        iterations_used: int,
        time_used_secs: float,
        is_complete: bool,
    ) -> ScoreInputs:
        # V0 dry-run: ending == starting; execution_quality is informational only.
        eq = (ending_value / starting_value) if starting_value > 0 else 0.0
        return ScoreInputs(
            completed_required_actions=is_complete,
            completion_rate=1.0 if is_complete else 0.0,
            invalid_run=not is_complete,
            execution_quality=eq,
            ending_value_delta=ending_value - starting_value,
            iterations_used=iterations_used,
            time_used_secs=time_used_secs,
        )

    # ----- V0 4-hook adapter surface (spec §5.4) -----

    def allowed_action_types(self) -> set[AgentActionType]:
        return {AgentActionType.FINISH, AgentActionType.WAIT}

    def should_flatten(self) -> bool:
        return False

    def compute_ending_value(self, run, final_balances: dict[str, int]) -> int:
        """V0 dry-run: ending == starting because no execution occurred."""
        return getattr(run, "starting_value", 0) or 0

    async def emit_run_evidence(self, db, run, events: list[dict]) -> None:
        """Lands in Task 15. For Task 13 / 14 this is a no-op stub."""
        return None
