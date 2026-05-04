"""RunnerService — benchmark execution orchestration.

Implements the core loop: observe → decide → validate → execute → persist.
After loop termination: flatten → finalize.

Event ordering: monotonically increasing sequence_no, persisted at each phase.
Deterministic: run_log_hash = SHA-256 of ordered events with canonical JSON.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.challenges.base import ChallengeState, CompletionResult, ScoreInputs
from src.challenges.swap_execution import SwapExecutionChallenge
from src.challenges.rebalance_execution import RebalanceExecutionChallenge

from src.chain.program_client import AgentArenaClient
from src.config import settings
from src.db.models import Challenge, Run, RunEvent
from src.db.schemas import AgentAction, AgentActionType
from src.integrity.action_validator import ActionValidator
from src.integrity.completion_evaluator import CompletionEvaluator
from src.providers.local_provider import ActionParseError
from src.services.swap_service_protocol import SwapServiceProtocol
from src.services.wallet_service import WalletService

logger = logging.getLogger(__name__)


# Shared serialization — single source of truth
from src.services.serialization import (  # noqa: E402
    EventJSONEncoder,
    compute_run_log_hash as _compute_hash,
    serialize_payload as _serialize_payload,
)


# ---------------------------------------------------------------------------
# Challenge dispatch (Task 12)
# ---------------------------------------------------------------------------


class UnknownChallengeTypeError(Exception):
    """Raised when execute_run sees an unrecognized challenge_type.

    Silent fallback to SwapExecutionChallenge is FORBIDDEN per spec §12 kill 4.
    """


CHALLENGE_ADAPTERS: dict[str, type] = {
    "swap_execution": SwapExecutionChallenge,
    "rebalance_execution": RebalanceExecutionChallenge,
}


# ---------------------------------------------------------------------------
# RunnerService
# ---------------------------------------------------------------------------


class RunnerService:
    """Orchestrates benchmark execution for a single run."""

    def __init__(
        self,
        db: AsyncSession,
        swap_service: SwapServiceProtocol,
        wallet_service: WalletService,
        program_client: AgentArenaClient | None = None,
    ):
        self.db = db
        self.swap = swap_service
        self.wallet = wallet_service
        self.program = program_client

    async def execute_run(
        self,
        run: Run,
        challenge: Challenge,
        provider: Any,  # AgentDecisionProvider
    ) -> Run:
        """Execute a complete benchmark run.

        1. Build challenge adapter and initial state
        2. Run the decision loop
        3. Flatten non-USDC positions
        4. Finalize: read balance, hash events, update on-chain
        """
        config = json.loads(challenge.config_json)

        # Dispatch by challenge_type. Unknown types raise — no silent fallback.
        try:
            adapter_cls = CHALLENGE_ADAPTERS[run.challenge_type]
        except KeyError as e:
            raise UnknownChallengeTypeError(
                f"unknown challenge_type {run.challenge_type!r}; "
                f"CHALLENGE_ADAPTERS covers {sorted(CHALLENGE_ADAPTERS.keys())}"
            ) from e
        adapter = adapter_cls(config)

        validator = ActionValidator(self.swap, config)

        wallet_address = run.benchmark_wallet_address or ""
        wallet_id = run.benchmark_wallet_ref or ""

        state = await adapter.build_initial_state(wallet_address)
        sequence_no = 0
        events: list[dict[str, Any]] = []
        loop_start = time.monotonic()

        # Mark run as running
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await self.db.commit()

        # ----- MAIN LOOP -----
        try:
            while True:
                elapsed = time.monotonic() - loop_start
                state.elapsed_secs = elapsed

                # --- OBSERVE ---
                try:
                    balances = await self.wallet.get_token_balances(wallet_address)
                    state.portfolio = balances if balances else state.portfolio
                except Exception as e:
                    logger.warning("observe failed: %s", e)

                event = await self._persist_event(
                    run, sequence_no, "observe", events,
                    state_snapshot=asdict(state),
                )
                sequence_no += 1

                # --- BUDGET CHECK ---
                if state.iterations_used >= state.iteration_budget:
                    await self._persist_event(
                        run, sequence_no, "budget_exceeded", events,
                        result_payload={"reason": "iteration_limit", "limit": state.iteration_budget},
                    )
                    sequence_no += 1
                    break

                if elapsed >= state.time_budget_secs:
                    await self._persist_event(
                        run, sequence_no, "budget_exceeded", events,
                        result_payload={"reason": "time_limit", "limit": state.time_budget_secs},
                    )
                    sequence_no += 1
                    break

                # --- DECIDE ---
                try:
                    action = await provider.decide(state)
                except ActionParseError as e:
                    await self._persist_event(
                        run, sequence_no, "error", events,
                        result_payload={"error": str(e), "raw_response": e.raw_response[:500]},
                    )
                    sequence_no += 1
                    break
                except Exception as e:
                    await self._persist_event(
                        run, sequence_no, "error", events,
                        result_payload={"error": str(e)},
                    )
                    sequence_no += 1
                    break

                await self._persist_event(
                    run, sequence_no, "decide", events,
                    action_payload=action.model_dump(),
                )
                sequence_no += 1

                # --- FINISH ---
                if action.type == AgentActionType.FINISH:
                    await self._persist_event(
                        run, sequence_no, "finish", events,
                    )
                    sequence_no += 1
                    break

                # --- VALIDATE ---
                validation_state = {
                    "iterations_used": state.iterations_used,
                    "iteration_budget": state.iteration_budget,
                }
                validation = await validator.validate(
                    action.model_dump(), validation_state,
                )
                await self._persist_event(
                    run, sequence_no, "validate", events,
                    validation_payload={
                        "valid": validation.valid,
                        "reason": validation.reason,
                        "details": validation.details,
                        "action_type": action.type.value,
                    },
                )
                sequence_no += 1

                # Fail-closed: do not execute invalid actions
                if not validation.valid:
                    state.iterations_used += 1
                    continue

                # --- EXECUTE ---
                exec_result: dict[str, Any] = {}
                tx_signature: str | None = None
                quote_snapshot: dict[str, Any] | None = None

                if action.type == AgentActionType.EXECUTE_SWAP:
                    try:
                        quote_id = action.params.get("quote_id", "")
                        slippage = action.params.get("max_slippage_bps", 100)
                        tx_bytes = await self.swap.prepare_swap_transaction(
                            quote_id, wallet_address, slippage,
                        )
                        sig = await self.wallet.sign_and_send_transaction(
                            wallet_id, tx_bytes,
                        )
                        tx_signature = sig
                        # Include output_mint + quote snapshot for completion + audit
                        quote = self.swap.get_cached_quote(quote_id)
                        output_mint = quote.output_mint if quote else ""
                        quote_snapshot = quote.model_dump() if quote else None
                        exec_result = {
                            "executed": True,
                            "tx_signature": sig,
                            "quote_id": quote_id,
                            "output_mint": output_mint,
                            "input_mint": quote.input_mint if quote else "",
                            "in_amount": quote.in_amount if quote else 0,
                            "out_amount": quote.out_amount if quote else 0,
                        }
                        # Track completed swap in state
                        if output_mint:
                            state.completed_swaps.append(output_mint)
                    except Exception as e:
                        exec_result = {"executed": False, "error": str(e)}

                elif action.type == AgentActionType.WAIT:
                    wait_secs = min(action.params.get("seconds", 5), 60)
                    await asyncio.sleep(wait_secs)
                    exec_result = {"waited": wait_secs}

                await self._persist_event(
                    run, sequence_no, "execute", events,
                    execution_payload=exec_result,
                    tx_signature=tx_signature,
                    quote_snapshot_ref=_serialize_payload(quote_snapshot) if quote_snapshot else None,
                )
                sequence_no += 1

                state.iterations_used += 1

        except Exception as e:
            logger.error("Runner loop fatal error: %s", e)
            await self._persist_event(
                run, sequence_no, "error", events,
                result_payload={"error": str(e), "fatal": True},
            )
            sequence_no += 1

        # ----- FLATTEN -----
        flatten_results = await self._flatten_to_usdc(
            run, wallet_id, wallet_address, config.get("usdc_mint", ""),
            sequence_no, events,
        )
        sequence_no += flatten_results["next_sequence_no"]

        # ----- FINALIZE -----
        await self._finalize_run(
            run, adapter, events, sequence_no, loop_start,
            iterations_used=state.iterations_used,
        )

        return run

    # -------------------------------------------------------------------
    # Flatten
    # -------------------------------------------------------------------

    async def _flatten_to_usdc(
        self,
        run: Run,
        wallet_id: str,
        wallet_address: str,
        usdc_mint: str,
        start_seq: int,
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Auto-flatten all non-USDC positions back to USDC.

        Platform-enforced, not agent decision. Persists every attempt.
        """
        seq = 0
        try:
            balances = await self.wallet.get_token_balances(wallet_address)
        except Exception as e:
            await self._persist_event(
                run, start_seq, "flatten", events,
                result_payload={"error": f"Failed to read balances: {e}"},
            )
            return {"next_sequence_no": 1}

        for mint, balance in balances.items():
            if mint == usdc_mint or balance == 0:
                continue

            result: dict[str, Any] = {"mint": mint, "amount": balance}
            try:
                quotes = await self.swap.get_quotes(
                    mint, usdc_mint, balance, slippage_bps=100,
                )
                if not quotes:
                    result["error"] = "No quotes available"
                else:
                    tx_bytes = await self.swap.prepare_swap_transaction(
                        quotes[0].quote_id, wallet_address, 100,
                    )
                    sig = await self.wallet.sign_and_send_transaction(
                        wallet_id, tx_bytes,
                    )
                    result["tx_signature"] = sig
                    result["success"] = True
            except Exception as e:
                result["error"] = str(e)
                result["success"] = False

            await self._persist_event(
                run, start_seq + seq, "flatten", events,
                execution_payload=result,
                tx_signature=result.get("tx_signature"),
            )
            seq += 1

        return {"next_sequence_no": max(seq, 1) if seq > 0 else 0}

    # -------------------------------------------------------------------
    # Finalize
    # -------------------------------------------------------------------

    async def _finalize_run(
        self,
        run: Run,
        adapter: SwapExecutionChallenge,
        events: list[dict[str, Any]],
        sequence_no: int,
        loop_start: float,
        iterations_used: int = 0,
    ) -> None:
        """Finalize a run: read balance, hash events, update on-chain."""
        wallet_address = run.benchmark_wallet_address or ""
        now = datetime.now(timezone.utc)
        elapsed = time.monotonic() - loop_start

        # Read final USDC balance
        try:
            final_balances = await self.wallet.get_token_balances(wallet_address)
            usdc_mint = adapter.usdc_mint
            ending_value = final_balances.get(usdc_mint, 0)
        except Exception:
            final_balances = {}
            ending_value = 0

        run.ending_value = ending_value

        # Compute completion status via CompletionEvaluator (hash covers this)
        evaluator = CompletionEvaluator(adapter)
        completion = await evaluator.evaluate(
            events, final_balances, run_status=run.status,
        )
        run.completion_status = completion.status
        run.invalid_reason = completion.reason

        # Compute score inputs
        starting = run.starting_value or 0
        is_complete = completion.status == "complete"
        score_inputs = await adapter.compute_score_inputs(
            starting, ending_value, iterations_used, elapsed, is_complete,
        )
        run.score_inputs_json = _serialize_payload(asdict(score_inputs))

        # Persist finalize event — this is the last event INSIDE the hash boundary
        finalize_payload = {
            "ending_value": ending_value,
            "completion_status": completion.status,
            "completion_reason": completion.reason,
            "iterations_used": iterations_used,
        }
        await self._persist_event(
            run, sequence_no, "finalize", events,
            result_payload=finalize_payload,
        )

        # ---- HASH BOUNDARY ----
        # run_log_hash covers: all loop events + flatten events + finalize event
        # On-chain call happens AFTER hash so the real hash is sent.
        # Post-chain operational events are OUTSIDE the hash boundary.
        run.run_log_hash = self._compute_run_log_hash(events)

        # On-chain finalize with the REAL hash
        next_seq = sequence_no + 1
        if self.program is not None:
            try:
                completion_variant = {
                    "complete": "Complete",
                    "incomplete": "Incomplete",
                    "invalid": "Invalid",
                }.get(completion.status, "Invalid")

                tx_sig = await self.program.finalize_run(
                    challenge_id=run.challenge_id,
                    agent_id=run.agent_id,
                    ending_usdc=ending_value,
                    run_log_hash=bytes.fromhex(run.run_log_hash),
                    completion_status_variant=completion_variant,
                    iterations_used=iterations_used,
                )
                # Persist successful on-chain finalize — OUTSIDE hash boundary
                await self._persist_event(
                    run, next_seq, "onchain_finalize", [],
                    result_payload={
                        "tx_signature": str(tx_sig),
                        "run_log_hash": run.run_log_hash,
                    },
                    tx_signature=str(tx_sig),
                )
                next_seq += 1
            except Exception as e:
                logger.error("On-chain finalize failed: %s", e)
                await self._persist_event(
                    run, next_seq, "error", [],
                    result_payload={
                        "error": f"On-chain finalize failed: {e}",
                        "onchain_finalize_failed": True,
                    },
                )
                next_seq += 1

        # Update run status
        run.status = "completed"
        run.ended_at = now
        run.iterations_used = iterations_used

        await self.db.commit()

    # -------------------------------------------------------------------
    # Event persistence
    # -------------------------------------------------------------------

    async def _persist_event(
        self,
        run: Run,
        sequence_no: int,
        event_type: str,
        events_list: list[dict[str, Any]],
        state_snapshot: dict[str, Any] | None = None,
        action_payload: dict[str, Any] | None = None,
        validation_payload: dict[str, Any] | None = None,
        execution_payload: dict[str, Any] | None = None,
        result_payload: dict[str, Any] | None = None,
        tx_signature: str | None = None,
        quote_snapshot_ref: str | None = None,
    ) -> RunEvent:
        """Persist an event with guaranteed ordering."""
        now = datetime.now(timezone.utc)

        event_dict = {
            "run_id": run.run_id,
            "sequence_no": sequence_no,
            "event_type": event_type,
            "timestamp": now.isoformat(),
            "state_snapshot_json": state_snapshot,
            "action_payload_json": action_payload,
            "validation_payload_json": validation_payload,
            "execution_payload_json": execution_payload,
            "result_payload_json": result_payload,
            "tx_signature": tx_signature,
            "quote_snapshot_ref": quote_snapshot_ref,
        }
        events_list.append(event_dict)

        db_event = RunEvent(
            run_id=run.run_id,
            sequence_no=sequence_no,
            event_type=event_type,
            timestamp=now,
            state_snapshot_json=_serialize_payload(state_snapshot) if state_snapshot else None,
            action_payload_json=_serialize_payload(action_payload) if action_payload else None,
            validation_payload_json=_serialize_payload(validation_payload) if validation_payload else None,
            execution_payload_json=_serialize_payload(execution_payload) if execution_payload else None,
            result_payload_json=_serialize_payload(result_payload) if result_payload else None,
            tx_signature=tx_signature,
            quote_snapshot_ref=quote_snapshot_ref,
        )
        self.db.add(db_event)
        await self.db.flush()

        return db_event

    # -------------------------------------------------------------------
    # Deterministic hashing
    # -------------------------------------------------------------------

    @staticmethod
    def _compute_run_log_hash(events: list[dict[str, Any]]) -> str:
        """Compute SHA-256 of all run events in deterministic order.

        Delegates to shared serialization.compute_run_log_hash.
        """
        return _compute_hash(events)
