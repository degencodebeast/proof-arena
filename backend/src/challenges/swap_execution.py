"""SwapExecutionChallenge — V1 fixed-basket swap execution adapter.

Implements ChallengeAdapter for the swap_execution_v1 challenge type.
- All contestants start with identical USDC
- All face the same basket of required swaps
- After completion, platform auto-flattens all positions to USDC
- Winner = highest ending USDC value

IMPORTANT: swap_intents must be canonical Solana mint addresses
(e.g., "So11111111111111111111111111111111111111112"), NOT symbols
like "SOL". The runner records output_mint from Jupiter quotes which
are always mint addresses. validate_completion compares directly.
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


class SwapExecutionChallenge:
    """V1 challenge adapter for fixed-basket swap execution."""

    def __init__(self, config: dict[str, Any]):
        self.starting_usdc: int = config["starting_usdc"]
        self.swap_intents: list[str] = config.get("swap_intents", [])
        self.allowed_routes: list[list[str]] = config.get("allowed_routes", [])
        self.iteration_budget: int = config.get("iteration_budget", 20)
        self.time_budget_secs: int = config.get("time_budget_secs", 300)
        self.max_slippage_bps: int = config.get("max_slippage_bps", 100)
        self.usdc_mint: str = config.get("usdc_mint", "")

    async def build_initial_state(self, wallet_address: str) -> ChallengeState:
        """Build the initial state for a benchmark run."""
        return ChallengeState(
            portfolio={"USDC": self.starting_usdc},
            completed_swaps=[],
            required_swaps=list(self.swap_intents),
            iterations_used=0,
            elapsed_secs=0.0,
            iteration_budget=self.iteration_budget,
            time_budget_secs=self.time_budget_secs,
            status="active",
            extra={
                "wallet_address": wallet_address,
                "usdc_mint": self.usdc_mint,
                "max_slippage_bps": self.max_slippage_bps,
            },
        )

    async def list_available_actions(
        self, state: ChallengeState
    ) -> list[QuoteOption]:
        """List available actions — deferred to runner which calls Jupiter."""
        return []

    async def validate_completion(
        self,
        run_events: list[dict[str, Any]],
        final_balances: dict[str, int],
    ) -> CompletionResult:
        """Check if a run meets completion criteria.

        Requirements:
        1. All required swaps in swap_intents were completed
        2. Final balances are flattened to USDC (all non-USDC balances zero)
        """
        # Extract completed swap mints from execute events
        completed_mints: set[str] = set()
        for event in run_events:
            if event.get("event_type") == "execute":
                exec_payload = event.get("execution_payload_json")
                if exec_payload and isinstance(exec_payload, dict):
                    if exec_payload.get("executed"):
                        # Track the output mint of executed swaps
                        output_mint = exec_payload.get("output_mint", "")
                        if output_mint:
                            completed_mints.add(output_mint)

        # Check required swaps completed
        required = set(self.swap_intents)
        missing = required - completed_mints
        if missing:
            return CompletionResult(
                status="incomplete",
                reason="incomplete_required_actions",
                details={"missing_swaps": list(missing)},
            )

        # Check flattened to USDC
        for mint, balance in final_balances.items():
            if mint == self.usdc_mint:
                continue
            if balance > 0:
                return CompletionResult(
                    status="incomplete",
                    reason="flattening_failed",
                    details={"unflattened_mint": mint, "balance": balance},
                )

        return CompletionResult(status="complete")

    async def compute_score_inputs(
        self,
        starting_value: int,
        ending_value: int,
        iterations_used: int,
        time_used_secs: float,
        is_complete: bool,
    ) -> ScoreInputs:
        """Compute raw score inputs from run outcome. No ranking formula."""
        execution_quality = (
            ending_value / starting_value if starting_value > 0 else 0.0
        )
        return ScoreInputs(
            completed_required_actions=is_complete,
            completion_rate=1.0 if is_complete else 0.0,
            invalid_run=not is_complete,
            execution_quality=execution_quality,
            ending_value_delta=ending_value - starting_value,
            iterations_used=iterations_used,
            time_used_secs=time_used_secs,
        )

    def allowed_action_types(self) -> set[AgentActionType]:
        return {
            AgentActionType.EXECUTE_SWAP,
            AgentActionType.WAIT,
            AgentActionType.FINISH,
        }

    def should_flatten(self) -> bool:
        return True

    def compute_ending_value(self, run, final_balances: dict[str, int]) -> int:
        """V1-preserving: equivalent to runner's prior inline lookup."""
        return final_balances.get(self.usdc_mint, 0)

    async def emit_run_evidence(self, db, run, events: list[dict]) -> None:
        """V0 swap path emits no separate evidence artifact."""
        return None
