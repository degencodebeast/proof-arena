"""Task 8: Integrity Layer — ActionValidator and CompletionEvaluator tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.schemas import AgentAction, AgentActionType
from src.integrity import ValidationResult


# -----------------------------------------------------------------------
# 1. ActionValidator
# -----------------------------------------------------------------------


class TestActionValidator:
    def _make_validator(self, **config_overrides):
        from src.integrity.action_validator import ActionValidator
        from src.services.jupiter_service import QuoteOption

        default_quote = QuoteOption(
            quote_id="q1", input_mint="USDC", output_mint="SOL",
            in_amount=100, out_amount=90, slippage_bps=100,
            fetched_at="2025-01-01T00:00:00Z", route_data={},
        )

        mock_jupiter = MagicMock()
        mock_jupiter.is_quote_fresh = MagicMock(return_value=True)
        mock_jupiter.get_cached_quote = MagicMock(return_value=default_quote)

        config = {
            "max_slippage_bps": 500,
            "allowed_routes": [],
            "quote_max_age_secs": 30,
        }
        config.update(config_overrides)
        return ActionValidator(mock_jupiter, config), mock_jupiter

    @pytest.mark.asyncio
    async def test_finish_is_valid(self):
        v, _ = self._make_validator()
        r = await v.validate({"type": "FINISH", "params": {}}, {})
        assert r.valid

    @pytest.mark.asyncio
    async def test_unknown_action_type_rejected(self):
        v, _ = self._make_validator()
        r = await v.validate({"type": "INVALID_TYPE", "params": {}}, {})
        assert not r.valid
        assert "Unknown action type" in r.reason

    @pytest.mark.asyncio
    async def test_wait_valid_seconds(self):
        v, _ = self._make_validator()
        r = await v.validate({"type": "WAIT", "params": {"seconds": 30}}, {})
        assert r.valid

    @pytest.mark.asyncio
    async def test_wait_zero_rejected(self):
        v, _ = self._make_validator()
        r = await v.validate({"type": "WAIT", "params": {"seconds": 0}}, {})
        assert not r.valid

    @pytest.mark.asyncio
    async def test_wait_over_60_rejected(self):
        v, _ = self._make_validator()
        r = await v.validate({"type": "WAIT", "params": {"seconds": 61}}, {})
        assert not r.valid

    @pytest.mark.asyncio
    async def test_swap_missing_quote_id(self):
        v, _ = self._make_validator()
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"max_slippage_bps": 100}}, {},
        )
        assert not r.valid
        assert "Missing quote_id" in r.reason

    @pytest.mark.asyncio
    async def test_swap_stale_quote(self):
        v, jupiter = self._make_validator()
        jupiter.is_quote_fresh.return_value = False
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 100}},
            {},
        )
        assert not r.valid
        assert "stale_quote" in r.reason

    @pytest.mark.asyncio
    async def test_swap_slippage_too_high(self):
        v, _ = self._make_validator(max_slippage_bps=100)
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 101}},
            {},
        )
        assert not r.valid
        assert "Slippage" in r.reason

    @pytest.mark.asyncio
    async def test_swap_route_whitelist_rejected(self):
        from src.services.jupiter_service import QuoteOption

        v, jupiter = self._make_validator(
            allowed_routes=[["USDC", "SOL"]],
        )
        jupiter.get_cached_quote.return_value = QuoteOption(
            quote_id="q1", input_mint="USDC", output_mint="RAY",
            in_amount=100, out_amount=90, slippage_bps=100,
            fetched_at="2025-01-01T00:00:00Z", route_data={},
        )
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 100}},
            {},
        )
        assert not r.valid
        assert "not in allowed routes" in r.reason

    @pytest.mark.asyncio
    async def test_swap_route_whitelist_accepted(self):
        from src.services.jupiter_service import QuoteOption

        v, jupiter = self._make_validator(
            allowed_routes=[["USDC", "SOL"]],
        )
        jupiter.get_cached_quote.return_value = QuoteOption(
            quote_id="q1", input_mint="USDC", output_mint="SOL",
            in_amount=100, out_amount=90, slippage_bps=100,
            fetched_at="2025-01-01T00:00:00Z", route_data={},
        )
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 100}},
            {},
        )
        assert r.valid

    @pytest.mark.asyncio
    async def test_swap_iteration_budget_exceeded(self):
        v, _ = self._make_validator()
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 100}},
            {"iterations_used": 20, "iteration_budget": 20},
        )
        assert not r.valid
        assert "budget" in r.reason.lower()

    @pytest.mark.asyncio
    async def test_swap_valid(self):
        v, _ = self._make_validator()
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "q1", "max_slippage_bps": 100}},
            {"iterations_used": 0, "iteration_budget": 20},
        )
        assert r.valid


# -----------------------------------------------------------------------
# 2. CompletionEvaluator
# -----------------------------------------------------------------------


class TestCompletionEvaluator:
    def _make_evaluator(self, adapter_result=None):
        from src.integrity.completion_evaluator import CompletionEvaluator
        from src.challenges.base import CompletionResult

        mock_adapter = MagicMock()
        if adapter_result:
            mock_adapter.validate_completion = AsyncMock(return_value=adapter_result)
        else:
            mock_adapter.validate_completion = AsyncMock(
                return_value=CompletionResult(status="complete"),
            )
        return CompletionEvaluator(mock_adapter), mock_adapter

    @pytest.mark.asyncio
    async def test_too_many_invalid_attempts(self):
        ev, _ = self._make_evaluator()
        events = [
            {"event_type": "validate", "validation_payload_json": {"valid": False}}
        ] * 11
        r = await ev.evaluate(events, {})
        assert r.status == "invalid"
        assert r.reason == "invalid_action_attempts_exceeded"

    @pytest.mark.asyncio
    async def test_under_threshold_delegates(self):
        ev, _ = self._make_evaluator()
        events = [
            {"event_type": "validate", "validation_payload_json": {"valid": False}}
        ] * 5
        r = await ev.evaluate(events, {})
        assert r.status == "complete"  # Adapter says complete

    @pytest.mark.asyncio
    async def test_timeout_status(self):
        ev, _ = self._make_evaluator()
        r = await ev.evaluate([], {}, run_status="timeout")
        assert r.status == "incomplete"
        assert r.reason == "timeout_before_completion"

    @pytest.mark.asyncio
    async def test_critical_error(self):
        ev, _ = self._make_evaluator()
        events = [
            {"event_type": "error", "result_payload_json": {"fatal": True, "error": "crash"}},
        ]
        r = await ev.evaluate(events, {})
        assert r.status == "invalid"
        assert r.reason == "execution_error"

    @pytest.mark.asyncio
    async def test_non_fatal_error_delegates(self):
        ev, _ = self._make_evaluator()
        events = [
            {"event_type": "error", "result_payload_json": {"error": "minor"}},
        ]
        r = await ev.evaluate(events, {})
        assert r.status == "complete"

    @pytest.mark.asyncio
    async def test_delegates_to_adapter(self):
        from src.challenges.base import CompletionResult

        adapter_result = CompletionResult(
            status="incomplete", reason="incomplete_required_actions",
        )
        ev, adapter = self._make_evaluator(adapter_result=adapter_result)
        r = await ev.evaluate([], {"USDC": 1000})
        assert r.status == "incomplete"
        assert r.reason == "incomplete_required_actions"
        adapter.validate_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_json_string_payloads_parsed(self):
        """Validation payloads stored as JSON strings must be parsed."""
        ev, _ = self._make_evaluator()
        events = [
            {"event_type": "validate", "validation_payload_json": '{"valid": false}'},
        ] * 11
        r = await ev.evaluate(events, {})
        assert r.status == "invalid"

    @pytest.mark.asyncio
    async def test_budget_exceeded_event_causes_incomplete(self):
        """Budget exhaustion must cause incomplete, even if swaps are done."""
        ev, _ = self._make_evaluator()  # Adapter would say "complete"
        events = [
            {"event_type": "budget_exceeded", "result_payload_json": {"reason": "iteration_limit"}},
        ]
        r = await ev.evaluate(events, {})
        assert r.status == "incomplete"
        assert r.reason == "timeout_before_completion"

    @pytest.mark.asyncio
    async def test_time_budget_exceeded_causes_incomplete(self):
        ev, _ = self._make_evaluator()
        events = [
            {"event_type": "budget_exceeded", "result_payload_json": {"reason": "time_limit"}},
        ]
        r = await ev.evaluate(events, {})
        assert r.status == "incomplete"


# -----------------------------------------------------------------------
# 3. ActionValidator — quote existence
# -----------------------------------------------------------------------


class TestQuoteExistence:
    @pytest.mark.asyncio
    async def test_missing_quote_after_freshness(self):
        """Quote that passes freshness but is None must be rejected."""
        from src.integrity.action_validator import ActionValidator

        mock_jupiter = MagicMock()
        mock_jupiter.is_quote_fresh = MagicMock(return_value=True)
        mock_jupiter.get_cached_quote = MagicMock(return_value=None)  # Missing!

        v = ActionValidator(mock_jupiter, {"max_slippage_bps": 500})
        r = await v.validate(
            {"type": "EXECUTE_SWAP", "params": {"quote_id": "ghost", "max_slippage_bps": 100}},
            {},
        )
        assert not r.valid
        assert "not found" in r.reason.lower()


# -----------------------------------------------------------------------
# 4. Runner integration — invalid actions not executed
# -----------------------------------------------------------------------


class TestRunnerValidationIntegration:
    @pytest.mark.asyncio
    async def test_invalid_swap_not_executed(self):
        """Invalid action is logged as validation failure and NOT executed."""
        from src.services.runner_service import RunnerService
        from src.services.jupiter_service import JupiterService

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        mock_jupiter = MagicMock(spec=JupiterService)
        mock_jupiter.is_quote_fresh = MagicMock(return_value=False)  # Stale!
        mock_jupiter.get_cached_quote = MagicMock(return_value=None)
        mock_jupiter.get_quotes = AsyncMock(return_value=[])
        mock_jupiter.get_token_balances = AsyncMock(return_value={})

        mock_wallet = MagicMock()
        mock_wallet.get_token_balances = AsyncMock(return_value={"USDC_MINT": 1000})
        mock_wallet.sign_and_send_transaction = AsyncMock(return_value="should_not_be_called")

        runner = RunnerService(mock_db, mock_jupiter, mock_wallet)

        # Provider returns stale swap then FINISH
        call_count = 0
        async def mock_decide(state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AgentAction(
                    type=AgentActionType.EXECUTE_SWAP,
                    params={"quote_id": "stale_q", "max_slippage_bps": 100},
                )
            return AgentAction(type=AgentActionType.FINISH, params={})

        provider = MagicMock()
        provider.decide = AsyncMock(side_effect=mock_decide)

        run = MagicMock()
        run.run_id = 1
        run.challenge_id = 1
        run.agent_id = 1
        run.benchmark_wallet_address = "wallet"
        run.benchmark_wallet_ref = "w_id"
        run.starting_value = 1000
        run.status = "pending"
        run.iterations_used = 0

        challenge = MagicMock()
        challenge.config_json = json.dumps({
            "starting_usdc": 1000,
            "swap_intents": [],
            "usdc_mint": "USDC_MINT",
            "iteration_budget": 20,
            "time_budget_secs": 300,
        })

        await runner.execute_run(run, challenge, provider)

        # Wallet should NOT have been called for signing
        mock_wallet.sign_and_send_transaction.assert_not_called()

        # Validation failure event should exist
        validate_events = [
            call.args[0]
            for call in mock_db.add.call_args_list
            if hasattr(call.args[0], "event_type") and call.args[0].event_type == "validate"
        ]
        assert len(validate_events) >= 1
        # First validate event should show failure
        payload = json.loads(validate_events[0].validation_payload_json)
        assert payload["valid"] is False
        assert "stale" in payload["reason"].lower()


# -----------------------------------------------------------------------
# 4. Module imports
# -----------------------------------------------------------------------


class TestImports:
    def test_all(self):
        from src.integrity import (
            ActionValidator,
            CompletionEvaluator,
            ValidationResult,
        )

        assert all([ActionValidator, CompletionEvaluator, ValidationResult])

    def test_onchain_finalize_event_type(self):
        from src.db.schemas import RunEventType

        assert RunEventType.ONCHAIN_FINALIZE == "onchain_finalize"
