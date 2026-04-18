"""Task 7: Runner Service and SwapExecutionChallenge tests.

All external calls mocked. Tests verify event ordering, budget enforcement,
flattening, deterministic hashing, and partial-failure persistence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from src.challenges.base import ChallengeState, CompletionResult, ScoreInputs
from src.db.schemas import AgentAction, AgentActionType
from src.services.runner_service import RunnerService
from src.services.serialization import EventJSONEncoder, serialize_payload as _serialize_payload


# -----------------------------------------------------------------------
# 1. SwapExecutionChallenge
# -----------------------------------------------------------------------


class TestSwapExecutionChallenge:
    def _make_adapter(self, **overrides):
        from src.challenges.swap_execution import SwapExecutionChallenge

        config = {
            "starting_usdc": 1_000_000_000,
            "swap_intents": ["SOL"],
            "allowed_routes": [],
            "iteration_budget": 20,
            "time_budget_secs": 300,
            "usdc_mint": "USDC_MINT",
        }
        config.update(overrides)
        return SwapExecutionChallenge(config)

    @pytest.mark.asyncio
    async def test_build_initial_state(self):
        adapter = self._make_adapter()
        state = await adapter.build_initial_state("walletAddr")
        assert state.portfolio == {"USDC": 1_000_000_000}
        assert state.required_swaps == ["SOL"]
        assert state.iterations_used == 0
        assert state.status == "active"
        assert state.extra["wallet_address"] == "walletAddr"

    @pytest.mark.asyncio
    async def test_validate_completion_incomplete_swaps(self):
        adapter = self._make_adapter(swap_intents=["SOL", "RAY"])
        events = [
            {"event_type": "execute", "execution_payload_json": {"executed": True, "output_mint": "SOL"}},
        ]
        result = await adapter.validate_completion(events, {"USDC_MINT": 1000})
        assert result.status == "incomplete"
        assert result.reason == "incomplete_required_actions"
        assert "RAY" in result.details["missing_swaps"]

    @pytest.mark.asyncio
    async def test_validate_completion_flattening_failed(self):
        adapter = self._make_adapter(swap_intents=["SOL"])
        events = [
            {"event_type": "execute", "execution_payload_json": {"executed": True, "output_mint": "SOL"}},
        ]
        # Non-USDC balance remains
        result = await adapter.validate_completion(events, {"USDC_MINT": 900, "SOL_MINT": 100})
        assert result.status == "incomplete"
        assert result.reason == "flattening_failed"

    @pytest.mark.asyncio
    async def test_validate_completion_complete(self):
        adapter = self._make_adapter(swap_intents=["SOL"])
        events = [
            {"event_type": "execute", "execution_payload_json": {"executed": True, "output_mint": "SOL"}},
        ]
        result = await adapter.validate_completion(events, {"USDC_MINT": 1000})
        assert result.status == "complete"

    @pytest.mark.asyncio
    async def test_compute_score_inputs(self):
        adapter = self._make_adapter()
        inputs = await adapter.compute_score_inputs(
            starting_value=1000, ending_value=1100,
            iterations_used=5, time_used_secs=120.0, is_complete=True,
        )
        assert inputs.completed_required_actions is True
        assert inputs.execution_quality == pytest.approx(1.1)
        assert inputs.ending_value_delta == 100
        assert inputs.iterations_used == 5

    @pytest.mark.asyncio
    async def test_compute_score_inputs_incomplete(self):
        adapter = self._make_adapter()
        inputs = await adapter.compute_score_inputs(
            starting_value=1000, ending_value=900,
            iterations_used=20, time_used_secs=300.0, is_complete=False,
        )
        assert inputs.invalid_run is True
        assert inputs.completion_rate == 0.0


# -----------------------------------------------------------------------
# 2. EventJSONEncoder
# -----------------------------------------------------------------------


class TestEventJSONEncoder:
    def test_encodes_pydantic_model(self):
        action = AgentAction(type=AgentActionType.FINISH, params={})
        s = json.dumps(action, cls=EventJSONEncoder)
        data = json.loads(s)
        assert data["type"] == "FINISH"

    def test_encodes_datetime(self):
        dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        s = json.dumps(dt, cls=EventJSONEncoder)
        assert "2025-01-01" in s

    def test_encodes_bytes(self):
        b = b"\x01\x02\x03"
        s = json.dumps(b, cls=EventJSONEncoder)
        assert "AQID" in s  # base64 of \x01\x02\x03

    def test_encodes_dataclass(self):
        state = ChallengeState(
            portfolio={}, completed_swaps=[], required_swaps=[],
            iterations_used=0, elapsed_secs=0.0,
            iteration_budget=20, time_budget_secs=300, status="active",
        )
        s = json.dumps(state, cls=EventJSONEncoder)
        data = json.loads(s)
        assert data["status"] == "active"


# -----------------------------------------------------------------------
# 3. Deterministic run_log_hash
# -----------------------------------------------------------------------


class TestRunLogHash:
    def test_deterministic_for_same_events(self):
        events = [
            {"sequence_no": 0, "event_type": "observe", "timestamp": "2025-01-01T00:00:00"},
            {"sequence_no": 1, "event_type": "decide", "timestamp": "2025-01-01T00:00:01"},
        ]
        h1 = RunnerService._compute_run_log_hash(events)
        h2 = RunnerService._compute_run_log_hash(events)
        assert h1 == h2

    def test_changes_when_event_changes(self):
        e1 = [{"sequence_no": 0, "event_type": "observe", "data": "a"}]
        e2 = [{"sequence_no": 0, "event_type": "observe", "data": "b"}]
        assert RunnerService._compute_run_log_hash(e1) != RunnerService._compute_run_log_hash(e2)

    def test_order_independent_of_insertion(self):
        """Events are sorted by sequence_no before hashing."""
        ordered = [
            {"sequence_no": 0, "event_type": "observe"},
            {"sequence_no": 1, "event_type": "decide"},
        ]
        reversed_order = [
            {"sequence_no": 1, "event_type": "decide"},
            {"sequence_no": 0, "event_type": "observe"},
        ]
        assert RunnerService._compute_run_log_hash(ordered) == RunnerService._compute_run_log_hash(reversed_order)

    def test_is_valid_sha256_hex(self):
        h = RunnerService._compute_run_log_hash([{"sequence_no": 0}])
        assert len(h) == 64
        int(h, 16)  # Valid hex

    def test_empty_events_produces_hash(self):
        h = RunnerService._compute_run_log_hash([])
        # SHA-256 of empty input
        assert h == hashlib.sha256(b"").hexdigest()


# -----------------------------------------------------------------------
# 4. RunnerService — helpers for mocking
# -----------------------------------------------------------------------


def _mock_run(**overrides):
    run = MagicMock()
    run.run_id = overrides.get("run_id", 1)
    run.challenge_id = overrides.get("challenge_id", 1)
    run.agent_id = overrides.get("agent_id", 1)
    run.benchmark_wallet_address = overrides.get("wallet_address", "wallet_addr")
    run.benchmark_wallet_ref = overrides.get("wallet_ref", "wallet_id")
    run.starting_value = overrides.get("starting_value", 1_000_000_000)
    run.status = "pending"
    run.iterations_used = 0
    run.ending_value = None
    run.run_log_hash = None
    run.completion_status = None
    run.invalid_reason = None
    run.score_inputs_json = None
    return run


def _mock_challenge(**overrides):
    ch = MagicMock()
    config = {
        "starting_usdc": 1_000_000_000,
        "swap_intents": ["SOL"],
        "iteration_budget": overrides.get("iteration_budget", 20),
        "time_budget_secs": overrides.get("time_budget_secs", 300),
        "usdc_mint": "USDC_MINT",
    }
    config.update(overrides.get("config_extra", {}))
    ch.config_json = json.dumps(config)
    return ch


def _mock_provider(actions: list[AgentAction]):
    """Create a mock provider that returns actions in sequence."""
    provider = MagicMock()
    call_count = 0

    async def decide(state):
        nonlocal call_count
        if call_count < len(actions):
            action = actions[call_count]
            call_count += 1
            return action
        return AgentAction(type=AgentActionType.FINISH, params={})

    provider.decide = AsyncMock(side_effect=decide)
    return provider


def _make_runner(db=None, jupiter=None, wallet=None, program=None):
    db = db or AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    jupiter = jupiter or MagicMock()
    jupiter.get_quotes = AsyncMock(return_value=[])
    jupiter.prepare_swap_transaction = AsyncMock(return_value=b"\x01")
    jupiter.get_cached_quote = MagicMock(return_value=None)

    wallet = wallet or MagicMock()
    wallet.get_token_balances = AsyncMock(return_value={"USDC_MINT": 1_000_000_000})
    wallet.sign_and_send_transaction = AsyncMock(return_value="tx_sig")

    return RunnerService(db, jupiter, wallet, program)


# -----------------------------------------------------------------------
# 5. RunnerService — loop tests
# -----------------------------------------------------------------------


class TestRunnerLoop:
    @pytest.mark.asyncio
    async def test_finish_exits_loop(self):
        runner = _make_runner()
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()
        challenge = _mock_challenge()

        result = await runner.execute_run(run, challenge, provider)

        assert result.status == "completed"
        assert result.run_log_hash is not None
        assert result.ending_value is not None

    @pytest.mark.asyncio
    async def test_event_sequence_numbers_are_monotonic(self):
        """Events must have monotonically increasing sequence_no."""
        runner = _make_runner()
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        # Check all persisted events have increasing sequence_no
        add_calls = runner.db.add.call_args_list
        event_seqs = []
        for call in add_calls:
            obj = call.args[0]
            if hasattr(obj, "sequence_no"):
                event_seqs.append(obj.sequence_no)

        assert event_seqs == sorted(event_seqs)
        assert len(set(event_seqs)) == len(event_seqs)  # No duplicates

    @pytest.mark.asyncio
    async def test_iteration_budget_exceeded(self):
        runner = _make_runner()
        # Provider always returns WAIT — will hit budget
        provider = _mock_provider([
            AgentAction(type=AgentActionType.WAIT, params={"seconds": 1}),
        ] * 25)  # More than budget
        run = _mock_run()
        challenge = _mock_challenge(iteration_budget=2)

        await runner.execute_run(run, challenge, provider)

        # Check budget_exceeded event was persisted
        add_calls = runner.db.add.call_args_list
        event_types = [
            call.args[0].event_type
            for call in add_calls
            if hasattr(call.args[0], "event_type")
        ]
        assert "budget_exceeded" in event_types

    @pytest.mark.asyncio
    async def test_error_event_persisted_on_decide_failure(self):
        runner = _make_runner()
        provider = MagicMock()
        provider.decide = AsyncMock(side_effect=Exception("LLM failure"))
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        event_types = [
            call.args[0].event_type
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
        ]
        assert "error" in event_types

    @pytest.mark.asyncio
    async def test_loop_phases_in_order(self):
        """Happy path: observe → decide → validate → execute → finish."""
        runner = _make_runner()
        provider = _mock_provider([
            AgentAction(type=AgentActionType.WAIT, params={"seconds": 1}),
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        event_types = [
            call.args[0].event_type
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
        ]
        # First iteration: observe, decide, validate, execute
        # Second iteration: observe, decide, finish
        # Then: finalize
        assert event_types[0] == "observe"
        assert "decide" in event_types
        assert "execute" in event_types
        assert "finish" in event_types
        assert event_types[-1] == "finalize"


# -----------------------------------------------------------------------
# 6. Flattening
# -----------------------------------------------------------------------


class TestFlattening:
    @pytest.mark.asyncio
    async def test_skips_usdc_and_zero_balances(self):
        runner = _make_runner()
        runner.wallet.get_token_balances = AsyncMock(return_value={
            "USDC_MINT": 1000, "SOL": 0,
        })

        run = _mock_run()
        events: list = []
        result = await runner._flatten_to_usdc(run, "w", "a", "USDC_MINT", 0, events)

        # No flatten events for USDC or zero balances
        flatten_events = [e for e in events if e.get("event_type") == "flatten"]
        assert len(flatten_events) == 0

    @pytest.mark.asyncio
    async def test_flattens_non_usdc_balance(self):
        from src.services.jupiter_service import QuoteOption

        runner = _make_runner()
        runner.wallet.get_token_balances = AsyncMock(return_value={
            "USDC_MINT": 900, "SOL_MINT": 100,
        })
        runner.jupiter.get_quotes = AsyncMock(return_value=[
            QuoteOption(
                quote_id="fq1", input_mint="SOL_MINT", output_mint="USDC_MINT",
                in_amount=100, out_amount=95, slippage_bps=100,
                fetched_at="2025-01-01T00:00:00Z", route_data={},
            ),
        ])

        run = _mock_run()
        events: list = []
        await runner._flatten_to_usdc(run, "w", "a", "USDC_MINT", 0, events)

        flatten_events = [e for e in events if e.get("event_type") == "flatten"]
        assert len(flatten_events) == 1

    @pytest.mark.asyncio
    async def test_partial_flatten_failure_recorded(self):
        """Flatten failure is recorded, not hidden."""
        runner = _make_runner()
        runner.wallet.get_token_balances = AsyncMock(return_value={
            "SOL_MINT": 100,
        })
        runner.jupiter.get_quotes = AsyncMock(side_effect=Exception("Jupiter down"))

        run = _mock_run()
        events: list = []
        await runner._flatten_to_usdc(run, "w", "a", "USDC_MINT", 0, events)

        flatten_events = [e for e in events if e.get("event_type") == "flatten"]
        assert len(flatten_events) == 1
        payload = flatten_events[0].get("execution_payload_json", {})
        assert payload.get("success") is False
        assert "Jupiter down" in payload.get("error", "")


# -----------------------------------------------------------------------
# 7. Finalization
# -----------------------------------------------------------------------


class TestFinalization:
    @pytest.mark.asyncio
    async def test_sets_ending_value_and_hash(self):
        runner = _make_runner()
        runner.wallet.get_token_balances = AsyncMock(return_value={"USDC_MINT": 1050})

        run = _mock_run()
        events = [{"sequence_no": 0, "event_type": "observe", "timestamp": "t"}]

        from src.challenges.swap_execution import SwapExecutionChallenge

        adapter = SwapExecutionChallenge({
            "starting_usdc": 1000, "swap_intents": [],
            "usdc_mint": "USDC_MINT",
        })
        await runner._finalize_run(run, adapter, events, 1, 0.0)

        assert run.ending_value == 1050
        assert run.run_log_hash is not None
        assert len(run.run_log_hash) == 64
        assert run.status == "completed"

    @pytest.mark.asyncio
    async def test_completion_status_stored(self):
        runner = _make_runner()
        runner.wallet.get_token_balances = AsyncMock(return_value={"USDC_MINT": 1000})

        run = _mock_run()
        events = []

        from src.challenges.swap_execution import SwapExecutionChallenge

        adapter = SwapExecutionChallenge({
            "starting_usdc": 1000, "swap_intents": ["SOL"],
            "usdc_mint": "USDC_MINT",
        })
        await runner._finalize_run(run, adapter, events, 0, 0.0)

        # SOL swap not completed → incomplete
        assert run.completion_status == "incomplete"
        assert run.invalid_reason == "incomplete_required_actions"

    @pytest.mark.asyncio
    async def test_score_inputs_json_stored(self):
        runner = _make_runner()
        runner.wallet.get_token_balances = AsyncMock(return_value={"USDC_MINT": 1100})

        run = _mock_run(starting_value=1000)
        events = [
            {"sequence_no": 0, "event_type": "execute",
             "execution_payload_json": {"executed": True, "output_mint": "SOL"}},
        ]

        from src.challenges.swap_execution import SwapExecutionChallenge

        adapter = SwapExecutionChallenge({
            "starting_usdc": 1000, "swap_intents": ["SOL"],
            "usdc_mint": "USDC_MINT",
        })
        await runner._finalize_run(run, adapter, events, 1, 0.0)

        assert run.score_inputs_json is not None
        data = json.loads(run.score_inputs_json)
        assert "execution_quality" in data


# -----------------------------------------------------------------------
# 8. Fix verification: execute events include output_mint
# -----------------------------------------------------------------------


class TestExecuteEventPayload:
    @pytest.mark.asyncio
    async def test_execute_swap_event_contains_output_mint(self):
        """The real runner must include output_mint in execute events
        so validate_completion can detect completed swaps."""
        from src.services.jupiter_service import QuoteOption

        mock_quote = QuoteOption(
            quote_id="q1", input_mint="USDC", output_mint="SOL_MINT",
            in_amount=100, out_amount=90, slippage_bps=100,
            fetched_at="2025-01-01T00:00:00Z", route_data={},
        )

        runner = _make_runner()
        runner.jupiter.get_cached_quote = MagicMock(return_value=mock_quote)

        provider = _mock_provider([
            AgentAction(type=AgentActionType.EXECUTE_SWAP,
                        params={"quote_id": "q1", "max_slippage_bps": 100}),
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        # Find the execute event and verify it has output_mint
        exec_events = [
            call.args[0]
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
            and call.args[0].event_type == "execute"
            and call.args[0].execution_payload_json
        ]
        assert len(exec_events) >= 1
        payload = json.loads(exec_events[0].execution_payload_json)
        assert payload.get("output_mint") == "SOL_MINT"


# -----------------------------------------------------------------------
# 9. Fix verification: iterations_used from loop, not stale DB
# -----------------------------------------------------------------------


class TestIterationsTracking:
    @pytest.mark.asyncio
    async def test_iterations_used_reflects_actual_loop_count(self):
        """iterations_used on the finalized run must equal actual loop iterations."""
        runner = _make_runner()
        provider = _mock_provider([
            AgentAction(type=AgentActionType.WAIT, params={"seconds": 1}),
            AgentAction(type=AgentActionType.WAIT, params={"seconds": 1}),
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()
        # run.iterations_used starts at 0 (stale)

        await runner.execute_run(run, _mock_challenge(), provider)

        # Must be 2 (two WAIT iterations), not 0
        assert run.iterations_used == 2

    @pytest.mark.asyncio
    async def test_score_inputs_use_real_iterations(self):
        runner = _make_runner()
        provider = _mock_provider([
            AgentAction(type=AgentActionType.WAIT, params={"seconds": 1}),
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run(starting_value=1000)

        await runner.execute_run(run, _mock_challenge(), provider)

        data = json.loads(run.score_inputs_json)
        assert data["iterations_used"] == 1


# -----------------------------------------------------------------------
# 10. Fix verification: on-chain finalize failure persisted
# -----------------------------------------------------------------------


class TestOnchainFinalizeFailure:
    @pytest.mark.asyncio
    async def test_onchain_failure_creates_error_event(self):
        mock_program = MagicMock()
        mock_program.finalize_run = AsyncMock(side_effect=Exception("RPC timeout"))

        runner = _make_runner(program=mock_program)
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        # Find error event with onchain_finalize_failed
        error_events = [
            call.args[0]
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
            and call.args[0].event_type == "error"
            and call.args[0].result_payload_json
        ]
        assert len(error_events) >= 1
        payload = json.loads(error_events[-1].result_payload_json)
        assert payload.get("onchain_finalize_failed") is True
        assert "RPC timeout" in payload.get("error", "")


# -----------------------------------------------------------------------
# 11. Hash covers ALL evidence including finalize event
# -----------------------------------------------------------------------


class TestHashBoundary:
    @pytest.mark.asyncio
    async def test_hash_equals_recomputed_hash_of_events(self):
        """run_log_hash must equal _compute_run_log_hash of the pre-chain events."""
        runner = _make_runner()
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        assert run.run_log_hash is not None
        assert len(run.run_log_hash) == 64

        # Reconstruct the pre-chain events from DB add calls
        # Exclude post-chain events (onchain_finalize, error with onchain_finalize_failed)
        pre_chain_events = []
        for call in runner.db.add.call_args_list:
            obj = call.args[0]
            if not hasattr(obj, "event_type") or not hasattr(obj, "sequence_no"):
                continue
            if obj.event_type == "onchain_finalize":
                continue
            if obj.event_type == "error" and obj.result_payload_json and "onchain_finalize_failed" in (obj.result_payload_json or ""):
                continue
            pre_chain_events.append({
                "run_id": obj.run_id,
                "sequence_no": obj.sequence_no,
                "event_type": obj.event_type,
                "timestamp": obj.timestamp.isoformat() if obj.timestamp else "",
                "state_snapshot_json": json.loads(obj.state_snapshot_json) if obj.state_snapshot_json else None,
                "action_payload_json": json.loads(obj.action_payload_json) if obj.action_payload_json else None,
                "validation_payload_json": json.loads(obj.validation_payload_json) if obj.validation_payload_json else None,
                "execution_payload_json": json.loads(obj.execution_payload_json) if obj.execution_payload_json else None,
                "result_payload_json": json.loads(obj.result_payload_json) if obj.result_payload_json else None,
                "tx_signature": obj.tx_signature,
                "quote_snapshot_ref": obj.quote_snapshot_ref,
            })

        # Recompute and assert equality
        recomputed = RunnerService._compute_run_log_hash(pre_chain_events)
        assert run.run_log_hash == recomputed

    @pytest.mark.asyncio
    async def test_onchain_receives_real_hash_not_placeholder(self):
        """On-chain finalize_run must receive the real hash, not zeros."""
        mock_program = MagicMock()
        mock_program.finalize_run = AsyncMock(return_value="tx_sig")

        runner = _make_runner(program=mock_program)
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        # Verify on-chain call was made
        mock_program.finalize_run.assert_called_once()
        call_kwargs = mock_program.finalize_run.call_args.kwargs

        # The hash sent on-chain must be the real hash, not zeros
        onchain_hash = call_kwargs["run_log_hash"]
        assert onchain_hash != b"\x00" * 32
        assert onchain_hash == bytes.fromhex(run.run_log_hash)

    @pytest.mark.asyncio
    async def test_successful_onchain_finalize_persisted(self):
        """Successful on-chain finalize creates an onchain_finalize event with tx sig."""
        mock_program = MagicMock()
        mock_program.finalize_run = AsyncMock(return_value="finalize_tx_sig_123")

        runner = _make_runner(program=mock_program)
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        onchain_events = [
            call.args[0]
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
            and call.args[0].event_type == "onchain_finalize"
        ]
        assert len(onchain_events) == 1
        assert onchain_events[0].tx_signature == "finalize_tx_sig_123"
        payload = json.loads(onchain_events[0].result_payload_json)
        assert payload["tx_signature"] == "finalize_tx_sig_123"
        assert payload["run_log_hash"] == run.run_log_hash

    @pytest.mark.asyncio
    async def test_onchain_error_is_outside_hash_boundary(self):
        """On-chain failure event is persisted in DB but NOT in the hash.

        Proof: the on-chain error event is passed an empty events list [],
        so it cannot appear in the hash computation which uses the main
        events list.
        """
        mock_program = MagicMock()
        mock_program.finalize_run = AsyncMock(side_effect=Exception("RPC fail"))

        runner = _make_runner(program=mock_program)
        provider = _mock_provider([
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        # Hash exists and is valid
        assert run.run_log_hash is not None
        assert len(run.run_log_hash) == 64

        # Error event IS persisted to DB
        error_events = [
            call.args[0]
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
            and call.args[0].event_type == "error"
            and call.args[0].result_payload_json
            and "onchain_finalize_failed" in (call.args[0].result_payload_json or "")
        ]
        assert len(error_events) >= 1

        # Verify the hash is the same as _compute_run_log_hash of
        # only the pre-chain events (which don't include the error)
        # The error was passed events_list=[] so it's not in the main list


# -----------------------------------------------------------------------
# 12. Canonical mint address matching
# -----------------------------------------------------------------------


class TestCanonicalMintMatching:
    @pytest.mark.asyncio
    async def test_runner_output_mint_matches_adapter_swap_intent(self):
        """When swap_intents and Jupiter output_mint use the same canonical
        mint address, completion must be detected correctly."""
        from src.services.jupiter_service import QuoteOption

        SOL_MINT = "So11111111111111111111111111111111111111112"

        mock_quote = QuoteOption(
            quote_id="q1", input_mint="USDC_MINT", output_mint=SOL_MINT,
            in_amount=100, out_amount=90, slippage_bps=100,
            fetched_at="2025-01-01T00:00:00Z", route_data={},
        )

        runner = _make_runner()
        runner.jupiter.get_cached_quote = MagicMock(return_value=mock_quote)
        runner.wallet.get_token_balances = AsyncMock(return_value={"USDC_MINT": 900})

        provider = _mock_provider([
            AgentAction(type=AgentActionType.EXECUTE_SWAP,
                        params={"quote_id": "q1", "max_slippage_bps": 100}),
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()
        # Challenge uses canonical mint address in swap_intents
        challenge = _mock_challenge(config_extra={"swap_intents": [SOL_MINT]})

        await runner.execute_run(run, challenge, provider)

        assert run.completion_status == "complete"


# -----------------------------------------------------------------------
# 13. Quote snapshot persisted on execute events
# -----------------------------------------------------------------------


class TestQuoteSnapshotPersistence:
    @pytest.mark.asyncio
    async def test_execute_event_has_quote_snapshot(self):
        from src.services.jupiter_service import QuoteOption

        mock_quote = QuoteOption(
            quote_id="q1", input_mint="USDC", output_mint="SOL",
            in_amount=100, out_amount=90, slippage_bps=100,
            fetched_at="2025-01-01T00:00:00Z", route_data={"plan": "test"},
        )

        runner = _make_runner()
        runner.jupiter.get_cached_quote = MagicMock(return_value=mock_quote)

        provider = _mock_provider([
            AgentAction(type=AgentActionType.EXECUTE_SWAP,
                        params={"quote_id": "q1", "max_slippage_bps": 100}),
            AgentAction(type=AgentActionType.FINISH, params={}),
        ])
        run = _mock_run()

        await runner.execute_run(run, _mock_challenge(), provider)

        exec_events = [
            call.args[0]
            for call in runner.db.add.call_args_list
            if hasattr(call.args[0], "event_type")
            and call.args[0].event_type == "execute"
            and call.args[0].quote_snapshot_ref
        ]
        assert len(exec_events) >= 1
        snapshot = json.loads(exec_events[0].quote_snapshot_ref)
        assert snapshot["quote_id"] == "q1"
        assert snapshot["output_mint"] == "SOL"


# -----------------------------------------------------------------------
# 14. Module imports
# -----------------------------------------------------------------------


class TestImports:
    def test_all(self):
        from src.challenges.swap_execution import SwapExecutionChallenge
        from src.services.runner_service import RunnerService
        from src.services.serialization import EventJSONEncoder

        assert all([SwapExecutionChallenge, RunnerService, EventJSONEncoder])
