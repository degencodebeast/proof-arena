"""RebalanceExecutionChallenge — V0 dry-run / decision-only adapter.

V0 scope (spec §5.4 locked phrasing):
- Decision-only, not generalized tool-calling.
- Agent emits FINISH; the platform computes the deterministic rebalance plan.
- No live multi-leg execution.
- emit_run_evidence writes one rebalance_evidence_v1 VerificationArtifact at finalize.

Spec §5.5: canonical evidence JSON is stored inline in VerificationArtifact.uri_or_ref.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select

from src.challenges.base import (
    ChallengeState,
    CompletionResult,
    QuoteOption,
    ScoreInputs,
)
from src.db.models import Agent, AgentInstance, VerificationArtifact
from src.db.schemas import AgentActionType

# Synthetic-Agent bridge regexes — same shape as cats.wallet_safety
# (backend/src/integrity/cats/wallet_safety.py:_METADATA_RE / _PRIVY_RE).
_METADATA_RE = re.compile(r"^agent_instances/(?P<id>\d+)$")
_PRIVY_RE = re.compile(r"^instance:(?P<id>\d+)$")


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
        """Spec §5.5 — write one rebalance_evidence_v1 artifact (idempotent).

        Resolves `instance_id` deterministically here (no Task 19 deferral) via
        the existing synthetic-Agent bridge: Run → Agent → AgentInstance, parsing
        `agent.metadata_ref` (`agent_instances/{id}`) with `agent.privy_user_id`
        (`instance:{id}`) as fallback. This matches `cats.wallet_safety._resolve_instance`.
        """
        # Idempotency: skip if an artifact already exists for (run_id, type).
        existing = (
            await db.execute(
                select(VerificationArtifact).where(
                    VerificationArtifact.run_id == run.run_id,
                    VerificationArtifact.artifact_type == "rebalance_evidence_v1",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return

        # Resolve instance_id via the synthetic-Agent bridge.
        agent = await db.get(Agent, run.agent_id)
        if agent is None:
            raise RuntimeError(
                f"emit_run_evidence: cannot resolve Agent for run {run.run_id} "
                f"(agent_id={run.agent_id})"
            )
        instance_id: int | None = None
        if agent.metadata_ref:
            m = _METADATA_RE.match(agent.metadata_ref)
            if m:
                instance_id = int(m.group("id"))
        if instance_id is None and agent.privy_user_id:
            m = _PRIVY_RE.match(agent.privy_user_id)
            if m:
                instance_id = int(m.group("id"))
        if instance_id is None:
            raise RuntimeError(
                f"emit_run_evidence: synthetic-Agent bridge unparseable for run {run.run_id} "
                f"(agent_id={run.agent_id}, metadata_ref={agent.metadata_ref!r}, "
                f"privy_user_id={agent.privy_user_id!r})"
            )
        instance = await db.get(AgentInstance, instance_id)
        if instance is None:
            raise RuntimeError(
                f"emit_run_evidence: AgentInstance {instance_id} missing for run {run.run_id}"
            )

        # Build start_portfolio / prices_used from the latest observe event.
        start_portfolio: dict[str, int] = {}
        prices_used: dict[str, int | None] = {}
        for event in reversed(events):
            if event.get("event_type") == "observe":
                snap = event.get("state_snapshot_json") or {}
                start_portfolio = dict(snap.get("portfolio", {}))
                prices_used = dict(snap.get("extra", {}).get("prices_used", {}) or {})
                break

        # Spec §5.5/§5.6: prices_used must have an entry for every mint in
        # target_allocations or start_portfolio. Missing prices appear as None
        # (the null is what triggers the Cat-layer price_data_present_check to fail).
        mints_in_scope = set(self.target_allocations.keys()) | set(start_portfolio.keys())
        for mint in mints_in_scope:
            prices_used.setdefault(mint, None)
        for mint in self.allowed_token_universe:
            start_portfolio.setdefault(mint, 0)

        plan = self._compute_v0_plan(start_portfolio=start_portfolio, prices_used=prices_used)

        payload = {
            "evidence_schema_version": "rebalance_evidence_v1",
            "run_id": run.run_id,
            "instance_id": instance.instance_id,
            "template_key": "rebalance_executor_v1",
            "effective_envelope": {
                "allowed_token_universe": list(self.allowed_token_universe),
                "target_allocations": dict(self.target_allocations),
                "rebalance_threshold_bps": self.rebalance_threshold_bps,
                "max_slippage_bps": self.max_slippage_bps,
                "max_position_weight": self.max_position_weight,
                "max_trade_value": self.max_trade_value,
                "dry_run": self.dry_run,
            },
            "target_allocations": dict(self.target_allocations),
            "prices_used": prices_used,
            "start_portfolio": start_portfolio,
            "end_portfolio": dict(start_portfolio),  # V0 dry-run: end == start
            "legs": plan["legs"],
            "dry_run": self.dry_run,
            "summary": plan["summary"],
        }
        canonical_json = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        content_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        db.add(VerificationArtifact(
            run_id=run.run_id,
            artifact_type="rebalance_evidence_v1",
            uri_or_ref=canonical_json,
            content_hash=content_hash,
        ))
        await db.commit()

    # ----- V0 deterministic plan (spec §5.5) -----

    def _compute_v0_plan(
        self,
        start_portfolio: dict[str, int],
        prices_used: dict[str, int | None],
    ) -> dict:
        """Compute the deterministic V0 rebalance plan from start_portfolio and prices.

        All arithmetic is integer-only. V0 dry-run: no execution, end == start.
        """
        # Step 1: per-mint value in USDC base units (price=None → 0)
        value_map: dict[str, int] = {}
        for mint, balance in start_portfolio.items():
            price = prices_used.get(mint)
            if price is None:
                value_map[mint] = 0
            else:
                value_map[mint] = balance * price // 1_000_000

        # Step 2: total value
        total_value: int = sum(value_map.values())

        # Step 3 & 4: per-mint targets, deltas, and drift
        target_values: dict[str, int] = {}
        current_values: dict[str, int] = {}
        deltas: dict[str, int] = {}

        for mint in sorted(self.target_allocations):
            weight = self.target_allocations[mint]
            target_value = int(total_value * weight)
            current_value = value_map.get(mint, 0)
            target_values[mint] = target_value
            current_values[mint] = current_value
            deltas[mint] = target_value - current_value

        if total_value == 0:
            drift_bps_pre_run = 0
        else:
            drift_bps_pre_run = int(
                sum(abs(deltas[mint]) for mint in self.target_allocations)
                / total_value
                * 10000
            )

        # Step 5: build legs if drift meets threshold
        if drift_bps_pre_run < self.rebalance_threshold_bps:
            legs: list[dict] = []
        else:
            legs = []
            for mint in sorted(self.target_allocations):
                delta = deltas[mint]
                if delta == 0:
                    continue
                side = "BUY" if delta > 0 else "SELL"
                size_base_units = min(abs(delta), self.max_trade_value)
                legs.append({
                    "mint": mint,
                    "side": side,
                    "size_base_units": size_base_units,
                    "status": "planned",
                    "slippage_bps_realized": 0,
                })
            # Sort deterministically by mint string
            legs.sort(key=lambda leg: leg["mint"])

        # Steps 6 & 7: V0 dry-run — portfolio unchanged, drift unchanged
        return {
            "legs": legs,
            "summary": {
                "drift_bps_pre_run": drift_bps_pre_run,
                "drift_bps_post_run": drift_bps_pre_run,
                "total_traded_value_base_units": sum(leg["size_base_units"] for leg in legs),
                "max_leg_slippage_bps": max(
                    (leg["slippage_bps_realized"] for leg in legs),
                    default=0,
                ),
            },
            "start_portfolio": start_portfolio,
            "end_portfolio": start_portfolio,
            "prices_used": prices_used,
        }
